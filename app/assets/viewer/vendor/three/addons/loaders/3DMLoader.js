import {
	BufferAttribute,
	BufferGeometry,
	BufferGeometryLoader,
	CanvasTexture,
	ClampToEdgeWrapping,
	Color,
	DirectionalLight,
	DoubleSide,
	FileLoader,
	LinearFilter,
	Line,
	LineBasicMaterial,
	Loader,
	Matrix4,
	Mesh,
	MeshPhysicalMaterial,
	MeshStandardMaterial,
	Object3D,
	PointLight,
	Points,
	PointsMaterial,
	RectAreaLight,
	RepeatWrapping,
	SpotLight,
	Sprite,
	SpriteMaterial,
	TextureLoader,
	EquirectangularReflectionMapping
} from 'three';

import { EXRLoader } from '../loaders/EXRLoader.js';

const _taskCache = new WeakMap();
const _bufferGeometryLoader = new BufferGeometryLoader();

/**
 * A loader for Rhinoceros 3D files and objects.
 *
 * Rhinoceros is a 3D modeler used to create, edit, analyze, document, render,
 * animate, and translate NURBS curves, surfaces, breps, extrusions, point clouds,
 * as well as polygon meshes and SubD objects. `rhino3dm.js` is compiled to WebAssembly
 * from the open source geometry library `openNURBS`. The loader currently uses
 * `rhino3dm.js 8.32.1`.
 *
 * ```js
 * const loader = new Rhino3dmLoader();
 * loader.setLibraryPath( 'https://cdn.jsdelivr.net/npm/rhino3dm@8.32.1/' );
 *
 * const object = await loader.loadAsync( 'models/3dm/Rhino_Logo.3dm' );
 * scene.add( object );
 * ```
 *
 * @augments Loader
 * @three_import import { Rhino3dmLoader } from 'three/addons/loaders/3DMLoader.js';
 */
class Rhino3dmLoader extends Loader {

	/**
	 * Constructs a new Rhino 3DM loader.
	 *
	 * @param {LoadingManager} [manager] - The loading manager.
	 */
	constructor( manager ) {

		super( manager );

		// internals

		this.libraryPath = '';
		this.libraryPending = null;
		this.libraryBinary = null;
		this.libraryConfig = {};

		this.url = '';

		this.workerLimit = 4;
		this.workerPool = [];
		this.workerNextTaskID = 1;
		this.workerSourceURL = '';
		this.workerConfig = {};

		// Number of global subdivisions applied to SubD objects before meshing. Higher
		// values increase smoothness at the cost of (potentially very large) vertex counts.
		this.subdivisionLevel = 3;

		// PATCH(curve-accuracy): { relTol, arcStepDeg, maxPoints } — a chord tolerance
		// relative to each curve's own size, an arc step and a per-curve cap. The app's
		// quality levels live in app/assets/viewer/config.js.
		this.curveOptions = null;

		this.materials = [];
		this.warnings = [];

	}

	/**
	 * Path to a folder containing the JS and WASM libraries.
	 *
	 * @param {string} path - The library path to set.
	 * @return {Rhino3dmLoader} A reference to this loader.
	 */
	setLibraryPath( path ) {

		this.libraryPath = path;

		return this;

	}

	/**
	 * Sets the maximum number of Web Workers to be used during decoding.
	 * A lower limit may be preferable if workers are also for other
	 * tasks in the application.
	 *
	 * @param {number} workerLimit - The worker limit.
	 * @return {Rhino3dmLoader} A reference to this loader.
	 */
	setWorkerLimit( workerLimit ) {

		this.workerLimit = workerLimit;

		return this;

	}

	/**
	 * Sets the number of global subdivisions applied to SubD objects before they are
	 * meshed for display. The default is `3`. Large models with many SubD objects may
	 * benefit from a lower value to keep vertex counts manageable.
	 *
	 * @param {number} level - The subdivision level.
	 * @return {Rhino3dmLoader} A reference to this loader.
	 */
	setSubdivisionLevel( level ) {

		this.subdivisionLevel = level;

		return this;

	}

	/**
	 * Starts loading from the given URL and passes the loaded 3DM asset
	 * to the `onLoad()` callback.
	 *
	 * @param {string} url - The path/URL of the file to be loaded. This can also be a data URI.
	 * @param {function(Object3D)} onLoad - Executed when the loading process has been finished.
	 * @param {onProgressCallback} onProgress - Executed while the loading is in progress.
	 * @param {onErrorCallback} onError - Executed when errors occur.
	 */
	load( url, onLoad, onProgress, onError ) {

		const loader = new FileLoader( this.manager );

		loader.setPath( this.path );
		loader.setResponseType( 'arraybuffer' );
		loader.setRequestHeader( this.requestHeader );

		this.url = url;

		loader.load( url, ( buffer ) => {

			// Check for an existing task using this buffer. A transferred buffer cannot be transferred
			// again from this thread.
			if ( _taskCache.has( buffer ) ) {

				const cachedTask = _taskCache.get( buffer );

				return cachedTask.promise.then( onLoad ).catch( onError );

			}

			this.decodeObjects( buffer, url )
				.then( result => {

					result.userData.warnings = this.warnings;
					onLoad( result );

				 } )
				.catch( e => onError( e ) );

		}, onProgress, onError );

	}

	/**
	 * Prints debug messages to the browser console.
	 */
	debug() {

		console.log( 'Task load: ', this.workerPool.map( ( worker ) => worker._taskLoad ) );

	}

	/**
	 * Decodes the 3DM asset data with a Web Worker.
	 *
	 * @param {ArrayBuffer} buffer - The raw 3DM asset data as an array buffer.
	 * @param {string} url - The asset URL.
	 * @return {Promise<Object3D>} A Promise that resolved with the decoded 3D object.
	 */
	decodeObjects( buffer, url ) {

		let worker;
		let taskID;

		const taskCost = buffer.byteLength;

		const objectPending = this._getWorker( taskCost )
			.then( ( _worker ) => {

				worker = _worker;
				taskID = this.workerNextTaskID ++;

				return new Promise( ( resolve, reject ) => {

					worker._callbacks[ taskID ] = { resolve, reject };

					// PATCH(curve-accuracy): how finely the worker samples curves.
					worker.postMessage( { type: 'decode', id: taskID, buffer, subdivisionLevel: this.subdivisionLevel, curveOptions: this.curveOptions }, [ buffer ] );

				} );

			} )
			.then( ( message ) => this._createGeometry( message.data ) )
			.catch( e => {

				throw e;

			} );

		// Remove task from the task list.
		// Note: replaced '.finally()' with '.catch().then()' block - iOS 11 support (#19416)
		objectPending
			.catch( () => true )
			.then( () => {

				if ( worker && taskID ) {

					this._releaseTask( worker, taskID );


				}

			} );

		// Cache the task result.
		_taskCache.set( buffer, {

			url: url,
			promise: objectPending

		} );

		return objectPending;

	}

	/**
	 * Parses the given 3DM data and passes the loaded 3DM asset
	 * to the `onLoad()` callback.
	 *
	 * @param {ArrayBuffer} data - The raw 3DM asset data as an array buffer.
	 * @param {function(Object3D)} onLoad - Executed when the loading process has been finished.
	 * @param {onErrorCallback} onError - Executed when errors occur.
	 */
	parse( data, onLoad, onError ) {

		this.parseAsync( data ).then( onLoad ).catch( onError );

	}

	/**
	 * Parses the given 3DM data and returns a Promise that resolves with the loaded asset.
	 *
	 * @param {ArrayBuffer} data - The raw 3DM asset data as an array buffer.
	 * @return {Promise<Object3D>} A Promise that resolves with the decoded 3D object.
	 */
	parseAsync( data ) {

		return this.decodeObjects( data, '' ).then( result => {

			result.userData.warnings = this.warnings;
			return result;

		} );

	}

	_compareMaterials( material ) {

		const mat = {};
		mat.name = material.name;
		mat.color = {};
		mat.color.r = material.color.r;
		mat.color.g = material.color.g;
		mat.color.b = material.color.b;
		mat.type = material.type;
		mat.vertexColors = material.vertexColors;

		const json = JSON.stringify( mat );

		for ( let i = 0; i < this.materials.length; i ++ ) {

			const m = this.materials[ i ];
			const _mat = {};
			_mat.name = m.name;
			_mat.color = {};
			_mat.color.r = m.color.r;
			_mat.color.g = m.color.g;
			_mat.color.b = m.color.b;
			_mat.type = m.type;
			_mat.vertexColors = m.vertexColors;

			if ( JSON.stringify( _mat ) === json ) {

				return m;

			}

		}

		this.materials.push( material );

		return material;

	}

	_createMaterial( material, renderEnvironment ) {

		if ( material === undefined ) {

			return new MeshStandardMaterial( {
				color: new Color( 1, 1, 1 ),
				metalness: 0.8,
				name: Loader.DEFAULT_MATERIAL_NAME,
				side: DoubleSide
			} );

		}


		const mat = new MeshPhysicalMaterial( {

			color: new Color( material.diffuseColor.r / 255.0, material.diffuseColor.g / 255.0, material.diffuseColor.b / 255.0 ),
			emissive: new Color( material.emissionColor.r / 255.0, material.emissionColor.g / 255.0, material.emissionColor.b / 255.0 ),
			flatShading: material.disableLighting,
			ior: material.indexOfRefraction,
			name: material.name,
			reflectivity: material.reflectivity,
			opacity: 1.0 - material.transparency,
			side: DoubleSide,
			specularColor: new Color( material.specularColor.r / 255.0, material.specularColor.g / 255.0, material.specularColor.b / 255.0 ),
			transparent: material.transparency > 0 ? true : false

		} );

		mat.userData.id = material.id;

		if ( material.pbrSupported ) {

			const pbr = material.pbr;

			mat.anisotropy = pbr.anisotropic;
			mat.anisotropyRotation = pbr.anisotropicRotation;
			mat.color = new Color( pbr.baseColor.r, pbr.baseColor.g, pbr.baseColor.b );
			mat.clearcoat = pbr.clearcoat;
			mat.clearcoatRoughness = pbr.clearcoatRoughness;
			mat.metalness = pbr.metallic;
			mat.roughness = pbr.roughness;
			mat.sheen = pbr.sheen;
			mat.specularIntensity = pbr.specular;
			mat.thickness = pbr.subsurface;

			// Rhino PBR Opacity is coverage/alpha, not glass transmission, and is
			// 1 = opaque (glTF/Disney convention, matching three.js mat.opacity — unlike
			// the legacy Material.transparency used above, which is 0 = opaque). Map it
			// straight to opacity so it behaves as pure alpha; leave mat.transmission at
			// its default (0) rather than deriving glass from opacity. (RH3DM-190)
			mat.opacity = pbr.opacity;
			mat.transparent = pbr.opacity < 1.0;

		}

		const textureLoader = new TextureLoader();

		for ( let i = 0; i < material.textures.length; i ++ ) {

			const texture = material.textures[ i ];

			if ( texture.image !== null ) {

				const map = textureLoader.load( texture.image );


				switch ( texture.type ) {

					case 'Bump':

						mat.bumpMap = map;

						break;

					case 'Diffuse':

						mat.map = map;

						break;

					case 'Emap':

						mat.envMap = map;

						break;

					case 'Opacity':

						mat.transmissionMap = map;

						break;

					case 'Transparency':

						mat.alphaMap = map;
						mat.transparent = true;

						break;

					case 'PBR_Alpha':

						mat.alphaMap = map;
						mat.transparent = true;

						break;

					case 'PBR_AmbientOcclusion':

						mat.aoMap = map;

						break;

					case 'PBR_Anisotropic':

						mat.anisotropyMap = map;

						break;

					case 'PBR_BaseColor':

						mat.map = map;

						break;

					case 'PBR_Clearcoat':

						mat.clearcoatMap = map;

						break;

					case 'PBR_ClearcoatBump':

						mat.clearcoatNormalMap = map;

						break;

					case 'PBR_ClearcoatRoughness':

						mat.clearcoatRoughnessMap = map;

						break;

					case 'PBR_Displacement':

						mat.displacementMap = map;

						break;

					case 'PBR_Emission':

						mat.emissiveMap = map;

						break;

					case 'PBR_Metallic':

						mat.metalnessMap = map;

						break;

					case 'PBR_Roughness':

						mat.roughnessMap = map;

						break;

					case 'PBR_Sheen':

						mat.sheenColorMap = map;

						break;

					case 'PBR_Specular':

						mat.specularColorMap = map;

						break;

					case 'PBR_Subsurface':

						mat.thicknessMap = map;

						break;

					default:

						this.warnings.push( {
							message: `THREE.3DMLoader: No conversion exists for 3dm ${texture.type}.`,
							type: 'no conversion'
						} );

						break;

				}

				map.wrapS = texture.wrapU === 0 ? RepeatWrapping : ClampToEdgeWrapping;
				map.wrapT = texture.wrapV === 0 ? RepeatWrapping : ClampToEdgeWrapping;

				if ( texture.repeat ) {

					map.repeat.set( texture.repeat[ 0 ], texture.repeat[ 1 ] );

				}

			}

		}

		if ( renderEnvironment ) {

			new EXRLoader().load( renderEnvironment.image, function ( texture ) {

				texture.mapping = EquirectangularReflectionMapping;
				mat.envMap = texture;

			} );

		}

		return mat;

	}

	_createGeometry( data ) {

		const object = new Object3D();
		const instanceDefinitionObjects = [];
		const instanceDefinitions = [];
		const instanceReferences = [];

		object.userData[ 'layers' ] = data.layers;
		object.userData[ 'views' ] = data.views;
		object.userData[ 'namedViews' ] = data.namedViews;
		object.userData[ 'groups' ] = data.groups;
		object.userData[ 'strings' ] = data.strings;
		object.userData[ 'settings' ] = data.settings;
		object.userData.settings[ 'renderSettings' ] = data.renderSettings;
		object.userData[ 'objectType' ] = 'File3dm';

		object.name = this.url;

		let objects = data.objects;
		const materials = data.materials;

		for ( let i = 0; i < objects.length; i ++ ) {

			const obj = objects[ i ];
			const attributes = obj.attributes;

			switch ( obj.objectType ) {

				case 'InstanceDefinition':

					instanceDefinitions.push( obj );

					break;

				case 'InstanceReference':

					instanceReferences.push( obj );

					break;

				default:

					let matId = null;

					switch ( attributes.materialSource.name ) {

						case 'ObjectMaterialSource_MaterialFromLayer':
							//check layer index
							if ( attributes.layerIndex >= 0 ) {

								matId = data.layers[ attributes.layerIndex ].renderMaterialIndex;

							}

							break;

						case 'ObjectMaterialSource_MaterialFromObject':

							if ( attributes.materialIndex >= 0 ) {

								matId = attributes.materialIndex;

							}

							break;

					}

					let material = null;

					if ( matId >= 0 ) {

						const rMaterial = materials[ matId ];
						material = this._createMaterial( rMaterial, data.renderEnvironment );


					}

					const _object = this._createObject( obj, material );

					if ( _object === undefined ) {

						continue;

					}

					const layer = data.layers[ attributes.layerIndex ];

					_object.visible = layer ? data.layers[ attributes.layerIndex ].visible : true;

					if ( attributes.isInstanceDefinitionObject ) {

						instanceDefinitionObjects.push( _object );

					} else {

						object.add( _object );

					}

					break;

			}

		}

		for ( let i = 0; i < instanceDefinitions.length; i ++ ) {

			const iDef = instanceDefinitions[ i ];

			objects = [];

			for ( let j = 0; j < iDef.attributes.objectIds.length; j ++ ) {

				const objId = iDef.attributes.objectIds[ j ];

				for ( let p = 0; p < instanceDefinitionObjects.length; p ++ ) {

					const idoId = instanceDefinitionObjects[ p ].userData.attributes.id;

					if ( objId === idoId ) {

						objects.push( instanceDefinitionObjects[ p ] );

					}

				}

			}

			// Currently clones geometry and does not take advantage of instancing

			for ( let j = 0; j < instanceReferences.length; j ++ ) {

				const iRef = instanceReferences[ j ];

				if ( iRef.geometry.parentIdefId === iDef.attributes.id ) {

					const iRefObject = new Object3D();
					const xf = iRef.geometry.xform.array;

					const matrix = new Matrix4();
					matrix.set( ...xf );

					iRefObject.applyMatrix4( matrix );

					for ( let p = 0; p < objects.length; p ++ ) {

						iRefObject.add( objects[ p ].clone( true ) );

					}

					object.add( iRefObject );

				}

			}

		}

		object.name = '';
		return object;

	}

	/**
	 * Builds a BufferGeometry from a worker payload. Meshes decoded via the fast path
	 * arrive as transferable typed arrays (`format: 'buffers'`) and are assembled directly;
	 * everything else falls back to the three.js BufferGeometry JSON produced by
	 * `toThreejsJSON()` (older rhino3dm, point clouds, curves, …).
	 */
	_geometryFromData( data ) {

		if ( data && data.format === 'buffers' ) {

			const geometry = new BufferGeometry();

			if ( data.position && data.position.length ) geometry.setAttribute( 'position', new BufferAttribute( data.position, 3 ) );
			if ( data.normal && data.normal.length ) geometry.setAttribute( 'normal', new BufferAttribute( data.normal, 3 ) );
			if ( data.uv && data.uv.length ) geometry.setAttribute( 'uv', new BufferAttribute( data.uv, 2 ) );
			if ( data.color && data.color.length ) geometry.setAttribute( 'color', new BufferAttribute( data.color, 3 ) );
			if ( data.index && data.index.length ) geometry.setIndex( new BufferAttribute( data.index, 1 ) );

			return geometry;

		}

		return _bufferGeometryLoader.parse( data );

	}

	_createObject( obj, mat ) {

		const attributes = obj.attributes;

		let geometry, material, _color, color;

		switch ( obj.objectType ) {

			case 'Point':
			case 'PointSet':

				geometry = this._geometryFromData( obj.geometry );

				if ( geometry.hasAttribute( 'color' ) ) {

					material = new PointsMaterial( { vertexColors: true, sizeAttenuation: false, size: 2 } );

				} else {

					_color = attributes.drawColor;
					color = new Color( _color.r / 255.0, _color.g / 255.0, _color.b / 255.0 );
					material = new PointsMaterial( { color: color, sizeAttenuation: false, size: 2 } );

				}

				material = this._compareMaterials( material );

				const points = new Points( geometry, material );
				points.userData[ 'attributes' ] = attributes;
				points.userData[ 'objectType' ] = obj.objectType;

				if ( attributes.name ) {

					points.name = attributes.name;

				}

				return points;

			case 'Mesh':
			case 'Extrusion':
			case 'SubD':
			case 'Brep':

				if ( obj.geometry === null ) return;

				geometry = this._geometryFromData( obj.geometry );


				if ( mat === null ) {

					mat = this._createMaterial();

				}


				if ( geometry.hasAttribute( 'color' ) ) {

					mat.vertexColors = true;

				}

				mat = this._compareMaterials( mat );

				const mesh = new Mesh( geometry, mat );
				mesh.castShadow = attributes.castsShadows;
				mesh.receiveShadow = attributes.receivesShadows;
				mesh.userData[ 'attributes' ] = attributes;
				mesh.userData[ 'objectType' ] = obj.objectType;

				if ( attributes.name ) {

					mesh.name = attributes.name;

				}

				return mesh;

			case 'Curve':

				geometry = this._geometryFromData( obj.geometry );

				_color = attributes.drawColor;
				color = new Color( _color.r / 255.0, _color.g / 255.0, _color.b / 255.0 );

				material = new LineBasicMaterial( { color: color } );
				material = this._compareMaterials( material );

				const lines = new Line( geometry, material );
				lines.userData[ 'attributes' ] = attributes;
				lines.userData[ 'objectType' ] = obj.objectType;

				if ( attributes.name ) {

					lines.name = attributes.name;

				}

				return lines;

			case 'TextDot':

				geometry = obj.geometry;

				const ctx = document.createElement( 'canvas' ).getContext( '2d' );
				const font = `${geometry.fontHeight}px ${geometry.fontFace}`;
				ctx.font = font;
				const width = ctx.measureText( geometry.text ).width + 10;
				const height = geometry.fontHeight + 10;

				const r = window.devicePixelRatio;

				ctx.canvas.width = width * r;
				ctx.canvas.height = height * r;
				ctx.canvas.style.width = width + 'px';
				ctx.canvas.style.height = height + 'px';
				ctx.setTransform( r, 0, 0, r, 0, 0 );

				ctx.font = font;
				ctx.textBaseline = 'middle';
				ctx.textAlign = 'center';
				color = attributes.drawColor;
				ctx.fillStyle = `rgba(${color.r},${color.g},${color.b},${color.a})`;
				ctx.fillRect( 0, 0, width, height );
				ctx.fillStyle = 'white';
				ctx.fillText( geometry.text, width / 2, height / 2 );

				const texture = new CanvasTexture( ctx.canvas );
				texture.minFilter = LinearFilter;
				texture.generateMipmaps = false;
				texture.wrapS = ClampToEdgeWrapping;
				texture.wrapT = ClampToEdgeWrapping;

				material = new SpriteMaterial( { map: texture, depthTest: false } );
				const sprite = new Sprite( material );
				sprite.position.set( geometry.point[ 0 ], geometry.point[ 1 ], geometry.point[ 2 ] );
				sprite.scale.set( width / 10, height / 10, 1.0 );

				sprite.userData[ 'attributes' ] = attributes;
				sprite.userData[ 'objectType' ] = obj.objectType;

				if ( attributes.name ) {

					sprite.name = attributes.name;

				}

				return sprite;

			case 'Light':

				geometry = obj.geometry;

				let light;

				switch ( geometry.lightStyle.name ) {

					case 'LightStyle_WorldPoint':

						light = new PointLight();
						light.castShadow = attributes.castsShadows;
						light.position.set( geometry.location[ 0 ], geometry.location[ 1 ], geometry.location[ 2 ] );
						light.shadow.normalBias = 0.1;

						break;

					case 'LightStyle_WorldSpot':

						light = new SpotLight();
						light.castShadow = attributes.castsShadows;
						light.position.set( geometry.location[ 0 ], geometry.location[ 1 ], geometry.location[ 2 ] );
						light.target.position.set( geometry.direction[ 0 ], geometry.direction[ 1 ], geometry.direction[ 2 ] );
						light.angle = geometry.spotAngleRadians;
						light.shadow.normalBias = 0.1;

						break;

					case 'LightStyle_WorldRectangular':

						light = new RectAreaLight();
						const width = Math.abs( geometry.width[ 2 ] );
						const height = Math.abs( geometry.length[ 0 ] );
						light.position.set( geometry.location[ 0 ] - ( height / 2 ), geometry.location[ 1 ], geometry.location[ 2 ] - ( width / 2 ) );
						light.height = height;
						light.width = width;
						light.lookAt( geometry.direction[ 0 ], geometry.direction[ 1 ], geometry.direction[ 2 ] );

						break;

					case 'LightStyle_WorldDirectional':

						light = new DirectionalLight();
						light.castShadow = attributes.castsShadows;
						light.position.set( geometry.location[ 0 ], geometry.location[ 1 ], geometry.location[ 2 ] );
						light.target.position.set( geometry.direction[ 0 ], geometry.direction[ 1 ], geometry.direction[ 2 ] );
						light.shadow.normalBias = 0.1;

						break;

					case 'LightStyle_WorldLinear':
						// no conversion exists, warning has already been printed to the console
						break;

					default:
						break;

				}

				if ( light ) {

					light.intensity = geometry.intensity;
					_color = geometry.diffuse;
					color = new Color( _color.r / 255.0, _color.g / 255.0, _color.b / 255.0 );
					light.color = color;
					light.userData[ 'attributes' ] = attributes;
					light.userData[ 'objectType' ] = obj.objectType;

				}

				return light;

		}

	}

	_initLibrary() {

		if ( ! this.libraryPending ) {

			// Load rhino3dm wrapper.
			const jsLoader = new FileLoader( this.manager );
			jsLoader.setPath( this.libraryPath );
			const jsContent = new Promise( ( resolve, reject ) => {

				jsLoader.load( 'rhino3dm.js', resolve, undefined, reject );

			} );

			// Load rhino3dm WASM binary.
			const binaryLoader = new FileLoader( this.manager );
			binaryLoader.setPath( this.libraryPath );
			binaryLoader.setResponseType( 'arraybuffer' );
			const binaryContent = new Promise( ( resolve, reject ) => {

				binaryLoader.load( 'rhino3dm.wasm', resolve, undefined, reject );

			} );

			this.libraryPending = Promise.all( [ jsContent, binaryContent ] )
				.then( ( [ jsContent, binaryContent ] ) => {

					//this.libraryBinary = binaryContent;
					this.libraryConfig.wasmBinary = binaryContent;

					const fn = Rhino3dmWorker.toString();

					const body = [
						'/* rhino3dm.js */',
						jsContent,
						'/* worker */',
						fn.substring( fn.indexOf( '{' ) + 1, fn.lastIndexOf( '}' ) )
					].join( '\n' );

					this.workerSourceURL = URL.createObjectURL( new Blob( [ body ] ) );

				} );

		}

		return this.libraryPending;

	}

	_getWorker( taskCost ) {

		return this._initLibrary().then( () => {

			if ( this.workerPool.length < this.workerLimit ) {

				const worker = new Worker( this.workerSourceURL );

				worker._callbacks = {};
				worker._taskCosts = {};
				worker._taskLoad = 0;

				// PATCH(init-error): settles once the worker has instantiated rhino3dm, or
				// rejects when it cannot (WASM compile/memory failure, broken script). See PATCHES.md.
				worker._ready = new Promise( ( resolve, reject ) => {

					worker._readyResolve = resolve;
					worker._readyReject = reject;

				} );

				worker.onerror = ( event ) => {

					const message = { type: 'error', id: 0, error: { message: 'rhino3dm worker error: ' + ( event.message || 'unknown' ) } };
					worker._readyReject( message );
					for ( const id in worker._callbacks ) worker._callbacks[ id ].reject( message );

				};

				worker.postMessage( {
					type: 'init',
					libraryConfig: this.libraryConfig
				} );

				worker.onmessage = e => {

					const message = e.data;

					switch ( message.type ) {

						case 'warning':
							this.warnings.push( message.data );
							console.warn( message.data );
							break;

						case 'ready':
							// PATCH(init-error): rhino3dm is usable inside the worker.
							worker._readyResolve();
							break;

						case 'decode':
							worker._callbacks[ message.id ].resolve( message );
							break;

						case 'error':
							// PATCH(init-error): id 0 is the library initialisation itself, not a task.
							if ( message.id === 0 ) worker._readyReject( message );
							else worker._callbacks[ message.id ].reject( message );
							break;

						default:
							console.error( 'THREE.Rhino3dmLoader: Unexpected message, "' + message.type + '"' );

					}

				};

				this.workerPool.push( worker );

			} else {

				this.workerPool.sort( function ( a, b ) {

					return a._taskLoad > b._taskLoad ? - 1 : 1;

				} );

			}

			const worker = this.workerPool[ this.workerPool.length - 1 ];

			worker._taskLoad += taskCost;

			return worker;

		} );

	}

	_releaseTask( worker, taskID ) {

		worker._taskLoad -= worker._taskCosts[ taskID ];
		delete worker._callbacks[ taskID ];
		delete worker._taskCosts[ taskID ];

	}

	/**
	 * Frees internal resources. This method should be called
	 * when the loader is no longer required.
	 */
	dispose() {

		for ( let i = 0; i < this.workerPool.length; ++ i ) {

			this.workerPool[ i ].terminate();

		}

		this.workerPool.length = 0;

	}

}

/* WEB WORKER */

function Rhino3dmWorker() {

	let libraryPending;
	let libraryConfig;
	let rhino;
	let taskID;
	let initError; // PATCH(init-error)

	// PATCH(curve-accuracy): chord tolerance as a fraction of each curve's own size, arc step,
	// and the per-curve point cap, sent with every decode. See curveToPoints().
	const CURVE_DEFAULTS = { relTol: 5e-4, arcStepDeg: 3, maxPoints: 4000 };
	let curveTolerances = CURVE_DEFAULTS;

	// PATCH(annotations): dimension styles by id, looked up once per decode.
	let dimstyleCache = null;

	onmessage = function ( e ) {

		const message = e.data;

		switch ( message.type ) {

			case 'init':

				libraryConfig = message.libraryConfig;
				const wasmBinary = libraryConfig.wasmBinary;
				let RhinoModule;
				libraryPending = new Promise( function ( resolve, reject ) {

					/* Like Basis Loader */
					RhinoModule = { wasmBinary, onRuntimeInitialized: resolve };

					// PATCH(init-error): the factory's promise rejects when the WASM cannot be
					// instantiated; upstream drops it and every decode then waits forever.
					rhino3dm( RhinoModule ).catch( reject ); // eslint-disable-line no-undef

				 } ).then( () => {

					rhino = RhinoModule;
					self.postMessage( { type: 'ready' } ); // PATCH(init-error)

				 }, ( error ) => {

					// PATCH(init-error): report once with id 0 (not a task); decodes fail fast below.
					initError = new Error( 'rhino3dm failed to initialise: ' + ( error && error.message ? error.message : error ) );
					self.postMessage( { type: 'error', id: 0, error: { message: initError.message, stack: error && error.stack } } );

				 } );

				break;

			case 'decode':

				taskID = message.id;
				const buffer = message.buffer;
				const subdivisionLevel = message.subdivisionLevel;
				curveTolerances = message.curveOptions || CURVE_DEFAULTS; // PATCH(curve-accuracy)
				libraryPending.then( () => {

					try {

						if ( initError ) throw initError; // PATCH(init-error)

						const data = decodeObjects( rhino, buffer, subdivisionLevel );
						// Transfer the mesh typed arrays (fast path) instead of structure-cloning
						// them across the worker boundary.
						self.postMessage( { type: 'decode', id: message.id, data }, collectTransferables( data ) );

					} catch ( error ) {

						// Error objects don't always survive structured clone with their stack intact.
						self.postMessage( { type: 'error', id: message.id, error: { message: error.message, stack: error.stack } } );

					}

				} );

				break;

		}

	};

	// Converts a rhino3dm mesh or point cloud to a Three.js payload. When the wasm build
	// supports toThreejsBuffers (rhino3dm >= 8.32.1 for point clouds, >= 8.32 for meshes),
	// returns transferable typed arrays tagged `format: 'buffers'`; otherwise falls back to
	// the element-by-element BufferGeometry JSON.
	function meshToThreejs( geom ) {

		if ( typeof geom.toThreejsBuffers === 'function' ) {

			const b = geom.toThreejsBuffers( false );
			const g = { format: 'buffers', position: b.position };
			if ( b.normal ) g.normal = b.normal; // meshes always have normals; point clouds may not
			if ( b.index ) g.index = b.index; // meshes only (point clouds are non-indexed)
			if ( b.uv ) g.uv = b.uv;
			if ( b.color ) g.color = b.color;
			return g;

		}

		return geom.toThreejsJSON();

	}

	// Gathers the ArrayBuffers backing every fast-path mesh so postMessage can transfer
	// (move) them to the main thread instead of copying.
	function collectTransferables( data ) {

		const transfer = new Set();

		if ( data && data.objects ) {

			for ( const obj of data.objects ) {

				const g = obj.geometry;

				if ( g && g.format === 'buffers' ) {

					for ( const key of [ 'position', 'normal', 'uv', 'color', 'index' ] ) {

						if ( g[ key ] && g[ key ].buffer ) transfer.add( g[ key ].buffer );

					}

				}

			}

		}

		return Array.from( transfer );

	}

	function decodeObjects( rhino, buffer, subdivisionLevel ) {

		const arr = new Uint8Array( buffer );
		const doc = rhino.File3dm.fromByteArray( arr );

		// PATCH(invalid-file): rhino3dm returns null (no exception) when the bytes are not a
		// complete .3dm; without this the failure surfaces as a TypeError on `doc.objects()`.
		if ( ! doc ) throw new Error( 'Not a valid or complete .3dm file' );

		const objects = [];
		const materials = [];
		const layers = [];
		const views = [];
		const namedViews = [];
		const groups = [];
		const strings = [];

		//Handle objects

		const objs = doc.objects();
		const cnt = objs.count;

		dimstyleCache = new Map(); // PATCH(annotations)

		try {

			for ( let i = 0; i < cnt; i ++ ) {

				const _object = objs.get( i );

				const object = extractObjectData( _object, doc, subdivisionLevel );

				_object.delete();

				if ( object ) {

					objects.push( object );

				}

			}

		} finally {

			// PATCH(annotations): the looked-up styles are copies owned by this decode.
			for ( const style of dimstyleCache.values() ) if ( style ) style.delete();
			dimstyleCache = null;

		}

		// Handle instance definitions

		for ( let i = 0; i < doc.instanceDefinitions().count; i ++ ) {

			const idef = doc.instanceDefinitions().get( i );
			const idefAttributes = extractProperties( idef );
			idefAttributes.objectIds = idef.getObjectIds();

			objects.push( { geometry: null, attributes: idefAttributes, objectType: 'InstanceDefinition' } );

		}

		// Handle materials

		const textureTypes = [
			// rhino.TextureType.Bitmap,
			rhino.TextureType.Diffuse,
			rhino.TextureType.Bump,
			rhino.TextureType.Transparency,
			rhino.TextureType.Opacity,
			rhino.TextureType.Emap
		];

		const pbrTextureTypes = [
			rhino.TextureType.PBR_BaseColor,
			rhino.TextureType.PBR_Subsurface,
			rhino.TextureType.PBR_SubsurfaceScattering,
			rhino.TextureType.PBR_SubsurfaceScatteringRadius,
			rhino.TextureType.PBR_Metallic,
			rhino.TextureType.PBR_Specular,
			rhino.TextureType.PBR_SpecularTint,
			rhino.TextureType.PBR_Roughness,
			rhino.TextureType.PBR_Anisotropic,
			rhino.TextureType.PBR_Anisotropic_Rotation,
			rhino.TextureType.PBR_Sheen,
			rhino.TextureType.PBR_SheenTint,
			rhino.TextureType.PBR_Clearcoat,
			rhino.TextureType.PBR_ClearcoatBump,
			rhino.TextureType.PBR_ClearcoatRoughness,
			rhino.TextureType.PBR_OpacityIor,
			rhino.TextureType.PBR_OpacityRoughness,
			rhino.TextureType.PBR_Emission,
			rhino.TextureType.PBR_AmbientOcclusion,
			rhino.TextureType.PBR_Displacement
		];

		for ( let i = 0; i < doc.materials().count; i ++ ) {

			const _material = doc.materials().get( i );

			const material = extractProperties( _material );

			const textures = [];

			textures.push( ...extractTextures( _material, textureTypes, doc ) );

			material.pbrSupported = _material.physicallyBased().supported;

			if ( material.pbrSupported ) {

				textures.push( ...extractTextures( _material, pbrTextureTypes, doc ) );
				material.pbr = extractProperties( _material.physicallyBased() );

			}

			material.textures = textures;

			materials.push( material );

			_material.delete();

		}

		// Handle layers

		for ( let i = 0; i < doc.layers().count; i ++ ) {

			const _layer = doc.layers().get( i );
			const layer = extractProperties( _layer );

			layers.push( layer );

			_layer.delete();

		}

		// Handle views

		for ( let i = 0; i < doc.views().count; i ++ ) {

			const _view = doc.views().get( i );
			const view = extractProperties( _view );

			views.push( view );

			_view.delete();

		}

		// Handle named views

		for ( let i = 0; i < doc.namedViews().count; i ++ ) {

			const _namedView = doc.namedViews().get( i );
			const namedView = extractProperties( _namedView );

			namedViews.push( namedView );

			_namedView.delete();

		}

		// Handle groups

		for ( let i = 0; i < doc.groups().count; i ++ ) {

			const _group = doc.groups().get( i );
			const group = extractProperties( _group );

			groups.push( group );

			_group.delete();

		}

		// Handle settings

		const settings = extractProperties( doc.settings() );

		//TODO: Handle other document stuff like dimstyles, instance definitions, bitmaps etc.

		// Handle dimstyles

		// Handle bitmaps

		// Handle strings
		// Note: doc.strings().documentUserTextCount() counts any doc.strings defined in a section

		const strings_count = doc.strings().count;

		for ( let i = 0; i < strings_count; i ++ ) {

			strings.push( doc.strings().get( i ) );

		}

		// Handle Render Environments for Material Environment

		// get the id of the active render environment skylight, which we'll use for environment texture
		const reflectionId = doc.settings().renderSettings().renderEnvironments.reflectionId;

		const rc = doc.renderContent();

		let renderEnvironment = null;

		for ( let i = 0; i < rc.count; i ++ ) {

			const content = rc.get( i );

			switch ( content.kind ) {

				case 'environment':

					const id = content.id;

					// there could be multiple render environments in a 3dm file
					if ( id !== reflectionId ) break;

					const renderTexture = content.findChild( 'texture' );
					const fileName = renderTexture.fileName;

					for ( let j = 0; j < doc.embeddedFiles().count; j ++ ) {

						const _fileName = doc.embeddedFiles().get( j ).fileName;

						if ( fileName === _fileName ) {

							const background = doc.getEmbeddedFileAsBase64( fileName );
							const backgroundImage = 'data:image/png;base64,' + background;
							renderEnvironment = { type: 'renderEnvironment', image: backgroundImage, name: fileName };

						}

					}

					break;

			}

		}

		// Handle Render Settings

		const renderSettings = {
			ambientLight: doc.settings().renderSettings().ambientLight,
			backgroundColorTop: doc.settings().renderSettings().backgroundColorTop,
			backgroundColorBottom: doc.settings().renderSettings().backgroundColorBottom,
			useHiddenLights: doc.settings().renderSettings().useHiddenLights,
			depthCue: doc.settings().renderSettings().depthCue,
			flatShade: doc.settings().renderSettings().flatShade,
			renderBackFaces: doc.settings().renderSettings().renderBackFaces,
			renderPoints: doc.settings().renderSettings().renderPoints,
			renderCurves: doc.settings().renderSettings().renderCurves,
			renderIsoParams: doc.settings().renderSettings().renderIsoParams,
			renderMeshEdges: doc.settings().renderSettings().renderMeshEdges,
			renderAnnotations: doc.settings().renderSettings().renderAnnotations,
			useViewportSize: doc.settings().renderSettings().useViewportSize,
			scaleBackgroundToFit: doc.settings().renderSettings().scaleBackgroundToFit,
			transparentBackground: doc.settings().renderSettings().transparentBackground,
			imageDpi: doc.settings().renderSettings().imageDpi,
			shadowMapLevel: doc.settings().renderSettings().shadowMapLevel,
			namedView: doc.settings().renderSettings().namedView,
			snapShot: doc.settings().renderSettings().snapShot,
			specificViewport: doc.settings().renderSettings().specificViewport,
			groundPlane: extractProperties( doc.settings().renderSettings().groundPlane ),
			safeFrame: extractProperties( doc.settings().renderSettings().safeFrame ),
			dithering: extractProperties( doc.settings().renderSettings().dithering ),
			skylight: extractProperties( doc.settings().renderSettings().skylight ),
			linearWorkflow: extractProperties( doc.settings().renderSettings().linearWorkflow ),
			renderChannels: extractProperties( doc.settings().renderSettings().renderChannels ),
			sun: extractProperties( doc.settings().renderSettings().sun ),
			renderEnvironments: extractProperties( doc.settings().renderSettings().renderEnvironments ),
			postEffects: extractProperties( doc.settings().renderSettings().postEffects ),

		};

		doc.delete();

		return { objects, materials, layers, views, namedViews, groups, strings, settings, renderSettings, renderEnvironment };

	}

	function extractTextures( m, tTypes, d ) {

		const textures = [];

		for ( let i = 0; i < tTypes.length; i ++ ) {

			const _texture = m.getTexture( tTypes[ i ] );
			if ( _texture ) {

				let textureType = tTypes[ i ].constructor.name;
				textureType = textureType.substring( 12, textureType.length );
				const texture = extractTextureData( _texture, textureType, d );
				textures.push( texture );
				_texture.delete();

			}

		}

		return textures;

	}

	function extractTextureData( t, tType, d ) {

		const texture = { type: tType };

		const image = d.getEmbeddedFileAsBase64( t.fileName );

		texture.wrapU = t.wrapU;
		texture.wrapV = t.wrapV;
		texture.wrapW = t.wrapW;
		const uvw = t.uvwTransform.toFloatArray( true );

		texture.repeat = [ uvw[ 0 ], uvw[ 5 ] ];

		if ( image ) {

			texture.image = 'data:image/png;base64,' + image;

		} else {

			self.postMessage( { type: 'warning', id: taskID, data: {
				message: `THREE.3DMLoader: Image for ${tType} texture not embedded in file.`,
				type: 'missing resource'
			}

			} );

			texture.image = null;

		}

		return texture;

	}

	function extractObjectData( object, doc, subdivisionLevel ) {

		const _geometry = object.geometry();
		const _attributes = object.attributes();
		let objectType = _geometry.objectType;
		let geometry, attributes, position, data, mesh;

		// skip instance definition objects
		//if( _attributes.isInstanceDefinitionObject ) { continue; }

		// TODO: handle other geometry types
		switch ( objectType ) {

			case rhino.ObjectType.Curve:

				const pts = curveToPoints( _geometry ); // PATCH(curve-accuracy): was a fixed 100 samples

				position = {};
				attributes = {};
				data = {};

				position.itemSize = 3;
				position.type = 'Float32Array';
				position.array = [];

				for ( let j = 0; j < pts.length; j ++ ) {

					position.array.push( pts[ j ][ 0 ] );
					position.array.push( pts[ j ][ 1 ] );
					position.array.push( pts[ j ][ 2 ] );

				}

				attributes.position = position;
				data.attributes = attributes;

				geometry = { data };

				break;

			case rhino.ObjectType.Point:

				const pt = _geometry.location;

				position = {};
				const color = {};
				attributes = {};
				data = {};

				position.itemSize = 3;
				position.type = 'Float32Array';
				position.array = [ pt[ 0 ], pt[ 1 ], pt[ 2 ] ];

				const _color = _attributes.drawColor( doc );

				color.itemSize = 3;
				color.type = 'Float32Array';
				color.array = [ _color.r / 255.0, _color.g / 255.0, _color.b / 255.0 ];

				attributes.position = position;
				attributes.color = color;
				data.attributes = attributes;

				geometry = { data };

				break;

			case rhino.ObjectType.PointSet:
			case rhino.ObjectType.Mesh:

				geometry = meshToThreejs( _geometry );

				break;

			case rhino.ObjectType.Brep:

				const faces = _geometry.faces();
				mesh = new rhino.Mesh();

				for ( let faceIndex = 0; faceIndex < faces.count; faceIndex ++ ) {

					const face = faces.get( faceIndex );
					const _mesh = face.getMesh( rhino.MeshType.Any );

					if ( _mesh ) {

						mesh.append( _mesh );
						_mesh.delete();

					}

					face.delete();

				}

				faces.delete();

				if ( mesh.faces().count > 0 ) {

					mesh.compact();
					geometry = meshToThreejs( mesh );

				} else {

					// PATCH(no-mesh): the file carries no cached render mesh for this Brep
					// ("Save small" or script-generated). Report it so the app can offer server meshing.
					mesh.delete();
					postNoMeshWarning( 'Brep', _attributes.id );
					return;

				}

				mesh.delete();

				break;

			case rhino.ObjectType.Extrusion:

				mesh = _geometry.getMesh( rhino.MeshType.Any );

				if ( mesh ) {

					geometry = meshToThreejs( mesh );
					mesh.delete();

				} else {

					// PATCH(no-mesh): see Brep case above.
					postNoMeshWarning( 'Extrusion', _attributes.id );
					return;

				}

				break;

			case rhino.ObjectType.TextDot:

				geometry = extractProperties( _geometry );

				break;

			case rhino.ObjectType.Light:

				geometry = extractProperties( _geometry );

				if ( geometry.lightStyle.name === 'LightStyle_WorldLinear' ) {

					self.postMessage( { type: 'warning', id: taskID, data: {
						message: `THREE.3DMLoader: No conversion exists for ${objectType.constructor.name} ${geometry.lightStyle.name}`,
						type: 'no conversion',
						guid: _attributes.id
					}

					} );

				}

				break;

			case rhino.ObjectType.InstanceReference:

				geometry = extractProperties( _geometry );
				geometry.xform = extractProperties( _geometry.xform );
				geometry.xform.array = _geometry.xform.toFloatArray( true );

				break;

			case rhino.ObjectType.SubD:

				// TODO: precalculate resulting vertices and faces and warn on excessive results
				_geometry.subdivide( subdivisionLevel );
				mesh = rhino.Mesh.createFromSubDControlNet( _geometry, false );
				if ( mesh ) {

					geometry = meshToThreejs( mesh );
					mesh.delete();

				}

				break;

			// PATCH(annotations): dimensions, text and leaders become lines, arrowheads and a
			// text placement; hatches become their boundary loops. Built on the main thread.
			case rhino.ObjectType.Annotation:

				geometry = extractAnnotation( _geometry, doc );

				break;

			case rhino.ObjectType.Hatch:

				geometry = extractHatch( _geometry );

				if ( ! geometry ) {

					self.postMessage( { type: 'warning', id: taskID, data: {
						message: 'THREE.3DMLoader: Hatch boundary could not be read.',
						type: 'no conversion',
						guid: _attributes.id
					}

					} );

					return;

				}

				break;

				/*
				case rhino.ObjectType.ClipPlane:
				*/

			default:

				self.postMessage( { type: 'warning', id: taskID, data: {
					message: `THREE.3DMLoader: Conversion not implemented for ${objectType.constructor.name}`,
					type: 'not implemented',
					guid: _attributes.id
				}

				} );

				break;

		}

		if ( geometry ) {

			attributes = extractProperties( _attributes );
			attributes.geometry = extractProperties( _geometry );

			if ( _attributes.groupCount > 0 ) {

				attributes.groupIds = _attributes.getGroupList();

			}

			if ( _attributes.userStringCount > 0 ) {

				attributes.userStrings = _attributes.getUserStrings();

			}

			if ( _geometry.userStringCount > 0 ) {

				attributes.geometry.userStrings = _geometry.getUserStrings();

			}

			if ( _attributes.decals().count > 0 ) {

				self.postMessage( { type: 'warning', id: taskID, data: {
					message: 'THREE.3DMLoader: No conversion exists for the decals associated with this object.',
					type: 'no conversion',
					guid: _attributes.id
				}

				} );

			}

			attributes.drawColor = _attributes.drawColor( doc );

			objectType = objectType.constructor.name;
			objectType = objectType.substring( 11, objectType.length );

			return { geometry, attributes, objectType };

		} else {

			self.postMessage( { type: 'warning', id: taskID, data: {
				message: `THREE.3DMLoader: ${objectType.constructor.name} has no associated mesh geometry.`,
				type: 'missing mesh',
				guid: _attributes.id
			}

			} );

		}

	}

	// PATCH(no-mesh): a Brep with zero meshed faces or an Extrusion without a mesh is
	// reported as `{ type: 'no mesh', objectType, guid, message }` (lands in
	// object.userData.warnings on the main thread). See PATCHES.md.
	function postNoMeshWarning( objectType, guid ) {

		self.postMessage( { type: 'warning', id: taskID, data: {
			message: `THREE.3DMLoader: ${objectType} ${guid} has no render mesh (file saved with "Save small" or written by a script).`,
			type: 'no mesh',
			objectType: objectType,
			guid: guid
		}

		} );

	}

	function extractProperties( object ) {

		const result = {};

		for ( const property in object ) {

			const value = object[ property ];

			if ( typeof value !== 'function' ) {

				if ( typeof value === 'object' && value !== null && value.hasOwnProperty( 'constructor' ) ) {

					result[ property ] = { name: value.constructor.name, value: value.value };

				} else if ( typeof value === 'object' && value !== null ) {

					result[ property ] = extractProperties( value );

				} else {

					result[ property ] = value;

				}

			} else {

				// these are functions that could be called to extract more data.

			}

		}

		return result;

	}

	// PATCH(curve-accuracy): curves are sampled adaptively against a chord tolerance relative
	// to each curve's own size (per knot span, arcs by angle) instead of a fixed 100 uniform
	// samples, so long or detailed curves keep their real shape. Returns [ [x, y, z], ... ].
	function curveToPoints( curve ) {

		const out = [];
		appendCurvePoints( curve, out, curveTolerance( curve ) );
		return out;

	}

	function curveTolerance( curve ) {

		let diag = 0;

		try {

			const box = curve.getBoundingBox();
			diag = Math.hypot( box.max[ 0 ] - box.min[ 0 ], box.max[ 1 ] - box.min[ 1 ], box.max[ 2 ] - box.min[ 2 ] );
			if ( typeof box.delete === 'function' ) box.delete();

		} catch ( e ) {

			diag = 0;

		}

		const tol = diag * curveTolerances.relTol;
		return tol > 0 && isFinite( tol ) ? tol : 1e-9;

	}

	function pushPoint( out, p ) {

		const last = out[ out.length - 1 ];
		if ( last && last[ 0 ] === p[ 0 ] && last[ 1 ] === p[ 1 ] && last[ 2 ] === p[ 2 ] ) return;
		out.push( [ p[ 0 ], p[ 1 ], p[ 2 ] ] );

	}

	function appendCurvePoints( curve, out, tol ) {

		if ( curve instanceof rhino.LineCurve ) {

			pushPoint( out, curve.pointAtStart );
			pushPoint( out, curve.pointAtEnd );
			return;

		}

		if ( curve instanceof rhino.PolylineCurve ) {

			for ( let i = 0; i < curve.pointCount; i ++ ) pushPoint( out, curve.point( i ) );
			return;

		}

		if ( curve instanceof rhino.PolyCurve ) {

			for ( let i = 0; i < curve.segmentCount; i ++ ) {

				const segment = curve.segmentCurve( i );
				appendCurvePoints( segment, out, tol );
				segment.delete();

			}

			return;

		}

		if ( curve instanceof rhino.ArcCurve ) {

			const count = Math.max( 2, Math.ceil( Math.abs( curve.angleDegrees ) / curveTolerances.arcStepDeg ) + 1 );
			const domain = curve.domain;
			for ( let j = 0; j < count; j ++ ) {

				pushPoint( out, curve.pointAt( domain[ 0 ] + ( j / ( count - 1 ) ) * ( domain[ 1 ] - domain[ 0 ] ) ) );

			}

			return;

		}

		const owned = ! ( curve instanceof rhino.NurbsCurve );
		const nurbs = owned ? curve.toNurbsCurve() : curve;
		if ( ! nurbs ) return;

		try {

			const params = spanParameters( nurbs );
			const limit = out.length + curveTolerances.maxPoints;
			// Straight spans need no subdivision; curved ones are always split a little so a
			// span whose midpoint happens to sit on the chord is still sampled.
			const minDepth = nurbs.degree <= 1 ? 0 : ( params.length > 64 ? 1 : 2 );
			let previous = nurbs.pointAt( params[ 0 ] );
			pushPoint( out, previous );

			for ( let s = 0; s + 1 < params.length; s ++ ) {

				const next = nurbs.pointAt( params[ s + 1 ] );
				subdivideSpan( nurbs, params[ s ], previous, params[ s + 1 ], next, tol * tol, 0, minDepth, out, limit );
				pushPoint( out, next );
				previous = next;

			}

		} finally {

			if ( owned ) nurbs.delete();

		}

	}

	// The increasing, distinct knot values inside the curve's domain, plus both ends.
	function spanParameters( nurbs ) {

		const domain = nurbs.domain;
		const eps = Math.abs( domain[ 1 ] - domain[ 0 ] ) * 1e-12;
		const params = [ domain[ 0 ] ];
		const knots = typeof nurbs.knots === 'function' ? nurbs.knots() : nurbs.knots;

		if ( knots ) {

			for ( let i = 0; i < knots.count; i ++ ) {

				const k = knots.get( i );
				if ( k > params[ params.length - 1 ] + eps && k < domain[ 1 ] - eps ) params.push( k );

			}

			if ( typeof knots.delete === 'function' ) knots.delete();

		}

		params.push( domain[ 1 ] );
		return params;

	}

	function subdivideSpan( curve, t0, p0, t1, p1, tol2, depth, minDepth, out, limit ) {

		if ( depth >= 10 || out.length >= limit ) return;

		const tm = ( t0 + t1 ) / 2;
		const pm = curve.pointAt( tm );

		if ( depth >= minDepth ) {

			const dx = pm[ 0 ] - ( p0[ 0 ] + p1[ 0 ] ) / 2;
			const dy = pm[ 1 ] - ( p0[ 1 ] + p1[ 1 ] ) / 2;
			const dz = pm[ 2 ] - ( p0[ 2 ] + p1[ 2 ] ) / 2;
			if ( dx * dx + dy * dy + dz * dz <= tol2 ) return;

		}

		subdivideSpan( curve, t0, p0, tm, pm, tol2, depth + 1, minDepth, out, limit );
		pushPoint( out, pm );
		subdivideSpan( curve, tm, pm, t1, p1, tol2, depth + 1, minDepth, out, limit );

	}

	// PATCH(annotations) ----------------------------------------------------------------
	// Annotations become { kind, text, plane, textHeight, textGap, font, normal, lines,
	// arrows, label }: world-space line segments (flat xyz pairs), arrowheads ({ tip, dir,
	// type, size }) and one text placement ({ point, dir, align, valign }). Built from the
	// definition points rhino3dm exposes; rhino3dm has no font metrics, so text extents and
	// the text gap in dimension lines are laid out on the main thread.

	function toXYZ( p ) {

		if ( ! p ) return null;
		if ( p.X !== undefined ) return [ p.X, p.Y, p.Z ];
		if ( p.length === 3 || p.length === 2 ) return [ p[ 0 ], p[ 1 ], p[ 2 ] || 0 ];
		return null;

	}

	function vAdd( a, b ) {

		return [ a[ 0 ] + b[ 0 ], a[ 1 ] + b[ 1 ], a[ 2 ] + b[ 2 ] ];

	}

	function vSub( a, b ) {

		return [ a[ 0 ] - b[ 0 ], a[ 1 ] - b[ 1 ], a[ 2 ] - b[ 2 ] ];

	}

	function vScale( a, s ) {

		return [ a[ 0 ] * s, a[ 1 ] * s, a[ 2 ] * s ];

	}

	function vDot( a, b ) {

		return a[ 0 ] * b[ 0 ] + a[ 1 ] * b[ 1 ] + a[ 2 ] * b[ 2 ];

	}

	function vLength( a ) {

		return Math.hypot( a[ 0 ], a[ 1 ], a[ 2 ] );

	}

	function vNormalize( a ) {

		const length = a ? vLength( a ) : 0;
		return length > 0 ? vScale( a, 1 / length ) : null;

	}

	function vCross( a, b ) {

		return [ a[ 1 ] * b[ 2 ] - a[ 2 ] * b[ 1 ], a[ 2 ] * b[ 0 ] - a[ 0 ] * b[ 2 ], a[ 0 ] * b[ 1 ] - a[ 1 ] * b[ 0 ] ];

	}

	function enumName( value, prefix ) {

		const name = value && value.constructor ? value.constructor.name : '';
		return name.startsWith( prefix ) ? name.substring( prefix.length ) : name;

	}

	function tryGet( fn ) {

		try {

			return fn();

		} catch ( e ) {

			return undefined;

		}

	}

	function dimstyleFor( doc, id ) {

		if ( ! dimstyleCache ) return null;
		if ( dimstyleCache.has( id ) ) return dimstyleCache.get( id );

		const table = doc.dimstyles();
		let style = tryGet( () => table.findId( id ) ) || null;
		// An annotation with per-object overrides may name a style that is not in the table.
		if ( ! style && table.count > 0 ) style = tryGet( () => table.get( 0 ) ) || null;
		// The table is not freed here: its `delete( id )` shadows the handle destructor.

		dimstyleCache.set( id, style );
		return style;

	}

	// Bold / italic and the font a Rhino rich-text string asks for. getFont() reports the
	// annotation's base font only, while the runs carry \b, \i and \fN.
	function rtfStyle( rtf ) {

		const result = { bold: false, italic: false, family: null };
		if ( ! rtf || rtf.indexOf( '{\\rtf' ) !== 0 ) return result;
		const fonts = {};
		const table = /\{\\fonttbl((?:\{[^{}]*\})*)\}/.exec( rtf );
		if ( table ) {

			for ( const m of table[ 1 ].matchAll( /\{\\f(\d+)[^ ;{}]*\s*([^;{}]+);?\}/g ) ) fonts[ m[ 1 ] ] = m[ 2 ].trim();

		}

		const body = table ? rtf.replace( table[ 0 ], '' ) : rtf;
		result.bold = /\\b(?![a-z0-9])/.test( body );
		result.italic = /\\i(?![a-z0-9])/.test( body );
		// The last font switch before the first text run wins.
		const used = [ ...body.matchAll( /\\f(\d+)(?![a-z0-9])/g ) ].map( ( m ) => m[ 1 ] );
		if ( used.length ) result.family = fonts[ used[ used.length - 1 ] ] || null;
		return result;

	}

	function fontOf( g, parentStyle, style ) {

		const out = { family: 'Arial', bold: false, italic: false };
		const f = tryGet( () => ( parentStyle && typeof g.getFont === 'function' ? g.getFont( parentStyle ) : style && style.getFont() ) );
		if ( f ) {

			if ( f.familyName ) out.family = f.familyName;
			out.bold = Boolean( tryGet( () => f.bold ) );
			out.italic = Boolean( tryGet( () => f.italic ) );
			if ( typeof f.delete === 'function' ) f.delete();

		}

		const rtf = rtfStyle( tryGet( () => g.richText ) );
		if ( rtf.family ) out.family = rtf.family;
		out.bold = out.bold || rtf.bold;
		out.italic = out.italic || rtf.italic;
		return out;

	}

	// Text justification. rhino3dm exposes none, but a style's own record (encode()) ends
	// with a fixed block whose int32 fields at 98, 94, 90 and 86 bytes from the end read
	// 1, vertical alignment, horizontal alignment, 1 - the same in Rhino 7 and 8 files.
	// Anything else falls back to Rhino's default, top left.
	const TEXT_VALIGN = [ 'top', 'middleOfTop', 'bottomOfTop', 'middle', 'middleOfBottom', 'bottom', 'bottomOfBox' ];
	const TEXT_HALIGN = [ 'left', 'center', 'right', 'left' ];

	function textAlignment( style ) {

		const fallback = { h: 'left', v: 'top' };
		const encoded = style ? tryGet( () => style.encode() ) : null;
		if ( ! encoded || ! encoded.data ) return fallback;
		const bytes = base64ToBytes( encoded.data );
		const n = bytes.length;
		if ( n < 110 ) return fallback;
		const view = new DataView( bytes.buffer, bytes.byteOffset, n );
		const at = ( k ) => view.getInt32( n - k, true );
		const v = at( 94 );
		const h = at( 90 );
		if ( at( 98 ) !== 1 || at( 86 ) !== 1 || ! ( v >= 0 && v < TEXT_VALIGN.length ) || ! ( h >= 0 && h < TEXT_HALIGN.length ) ) return fallback;
		return { h: TEXT_HALIGN[ h ], v: TEXT_VALIGN[ v ] };

	}

	function formatMeasurement( value, style, prefix ) {

		const factor = style && style.lengthFactor > 0 ? style.lengthFactor : 1;
		return prefix + ( value * factor ).toFixed( 1 );

	}

	function extractAnnotation( g, doc ) {

		const kind = enumName( g.annotationType, 'AnnotationTypes_' ) || 'Unset';
		const parentStyle = dimstyleFor( doc, g.dimensionStyleId );
		// rhino3dm >= 8.35 gives the object's effective style (its property overrides
		// applied), its text height and the model-space scale Rhino multiplies every
		// annotation length by; older builds fall back to the parent style.
		const ownStyle = parentStyle && typeof g.getDimensionStyle === 'function' ? tryGet( () => g.getDimensionStyle( parentStyle ) ) : null;

		try {

			const style = ownStyle || parentStyle;
			let scale = parentStyle && typeof g.getDimensionScale === 'function' ? tryGet( () => g.getDimensionScale( parentStyle ) ) : undefined;
			if ( ! ( scale > 0 ) ) scale = style && style.dimensionScale > 0 ? style.dimensionScale : 1;
			let baseHeight = parentStyle && typeof g.getTextHeight === 'function' ? tryGet( () => g.getTextHeight( parentStyle ) ) : undefined;
			if ( ! ( baseHeight > 0 ) ) baseHeight = style && style.textHeight > 0 ? style.textHeight : 1;
			const textHeight = baseHeight * scale;
			// A style length in model units: scaled, or `fallback` when the style has none.
			const len = ( value, fallback ) => ( Number.isFinite( value ) && value >= 0 ? value * scale : fallback );

			const plane = g.plane;
			const origin = toXYZ( plane.origin ) || [ 0, 0, 0 ];
			const xAxis = vNormalize( toXYZ( plane.xAxis ) ) || [ 1, 0, 0 ];
			const yAxis = vNormalize( toXYZ( plane.yAxis ) ) || [ 0, 1, 0 ];
			const font = fontOf( g, parentStyle, style );

			const out = {
				kind,
				text: tryGet( () => g.plainTextWithFields ) || tryGet( () => g.plainText ) || '',
				plane: { origin, xAxis, yAxis },
				normal: vNormalize( vCross( xAxis, yAxis ) ) || [ 0, 0, 1 ],
				textHeight,
				textGap: len( style && style.textGap, textHeight / 4 ),
				font: font.family,
				bold: font.bold,
				italic: font.italic,
				// Rhino's "draw forward": text turns to read left to right from the view.
				drawForward: ! ( style && style.drawForward === false ),
				lines: [],
				arrows: [],
				label: null
			};

			// The measured value in model units, so the app can show the dimension in any
			// unit, and Rhino's own formatting for text it has not formatted yet (a file
			// written before the annotation was ever drawn); "<>" stands for the measurement.
			const withMeasurement = ( value, prefix ) => {

				out.measure = { value: value, prefix: prefix };
				const measured = formatMeasurement( value, style, prefix );
				if ( ! out.text ) out.text = measured;
				else if ( out.text.indexOf( '<>' ) >= 0 ) out.text = out.text.split( '<>' ).join( measured );

			};

			const line = ( a, b ) => {

				if ( a && b ) out.lines.push( a[ 0 ], a[ 1 ], a[ 2 ], b[ 0 ], b[ 1 ], b[ 2 ] );

			};

			const arrow = ( tip, from, type, size ) => {

				const dir = tip && from ? vNormalize( vSub( tip, from ) ) : null;
				if ( dir && type !== 'None' ) out.arrows.push( { tip, dir, type: type || 'SolidTriangle', size: size > 0 ? size : textHeight } );

			};

			const pts = tryGet( () => g.points );

			switch ( kind ) {

				case 'Aligned':
				case 'Rotated': {

					const d1 = toXYZ( pts && pts.defpt1 );
					const d2 = toXYZ( pts && pts.defpt2 );
					let a1 = toXYZ( pts && pts.arrowpt1 );
					let a2 = toXYZ( pts && pts.arrowpt2 );
					const dimline = toXYZ( pts && pts.dimline );
					let textPoint = toXYZ( pts && pts.textpt );
					if ( ! a1 || ! a2 ) break;
					// Arrow points that coincide although the definition points do not (an
					// aligned dimension whose cached layout is stale): rebuild them from the
					// definition points and the dimension line point.
					if ( d1 && d2 && dimline && vLength( vSub( a2, a1 ) ) < 1e-9 && vLength( vSub( d2, d1 ) ) > 1e-9 ) {

						const along = vNormalize( vSub( d2, d1 ) );
						const rel = vSub( dimline, d1 );
						const off = vSub( rel, vScale( along, vDot( rel, along ) ) );
						a1 = vAdd( d1, off );
						a2 = vAdd( d2, off );
						textPoint = vScale( vAdd( a1, a2 ), 0.5 );

					}

					const offset = len( style && style.extensionLineOffset, 0 );
					const extension = len( style && style.extensionLineExtension, 0 );
					const extensionLine = ( from, to, suppressed ) => {

						const v = from ? vSub( to, from ) : null;
						const length = v ? vLength( v ) : 0;
						if ( suppressed || length < 1e-9 ) return;
						const u = vScale( v, 1 / length );
						line( vAdd( from, vScale( u, Math.min( offset, length ) ) ), vAdd( to, vScale( u, extension ) ) );

					};

					extensionLine( d1, a1, style && style.suppressExtension1 );
					extensionLine( d2, a2, style && style.suppressExtension2 );

					const axis = vNormalize( vSub( a2, a1 ) );
					if ( axis ) {

						// The dimension line runs between the arrows, and on to the text when the
						// text sits outside them. Not to `points.dimline`: that only fixes how far
						// the line sits from the definition points and can be far outside them
						// (KIOSK's 240.0 dimension has it 160 cm below the model).
						let t0 = 0;
						let t1 = vLength( vSub( a2, a1 ) );
						if ( textPoint ) {

							const t = vDot( vSub( textPoint, a1 ), axis );
							t0 = Math.min( t0, t );
							t1 = Math.max( t1, t );

						}

						out.dimensionLine = [ ...vAdd( a1, vScale( axis, t0 ) ), ...vAdd( a1, vScale( axis, t1 ) ) ];
						const arrowSize = len( style && style.arrowLength, textHeight );
						if ( ! ( style && style.suppressArrow1 ) ) arrow( a1, a2, enumName( style && style.arrowType1, 'ArrowheadTypes_' ), arrowSize );
						if ( ! ( style && style.suppressArrow2 ) ) arrow( a2, a1, enumName( style && style.arrowType2, 'ArrowheadTypes_' ), arrowSize );
						if ( d1 && d2 ) withMeasurement( Math.abs( vDot( vSub( d2, d1 ), axis ) ), '' );

					}

					out.label = { point: textPoint || vScale( vAdd( a1, a2 ), 0.5 ), dir: axis || xAxis, align: 'center', valign: 'above' };
					break;

				}

				case 'Radius':
				case 'Diameter': {

					const center = toXYZ( pts && pts.centerpt );
					const radius = toXYZ( pts && pts.radiuspt );
					const dimline = toXYZ( pts && pts.dimlinept );
					const knee = toXYZ( pts && pts.kneept ) || dimline;
					if ( ! radius || ! dimline ) break;

					line( radius, knee );
					if ( vLength( vSub( dimline, knee ) ) > 1e-9 ) line( knee, dimline );
					arrow( radius, knee, enumName( style && style.arrowType1, 'ArrowheadTypes_' ), len( style && style.arrowLength, textHeight ) );

					const mark = len( style && style.centermarkSize, 0 );
					if ( center && mark > 0 ) {

						line( vAdd( center, vScale( xAxis, - mark ) ), vAdd( center, vScale( xAxis, mark ) ) );
						line( vAdd( center, vScale( yAxis, - mark ) ), vAdd( center, vScale( yAxis, mark ) ) );

					}

					if ( center ) {

						const r = vLength( vSub( radius, center ) );
						withMeasurement( kind === 'Diameter' ? 2 * r : r, kind === 'Diameter' ? 'Ø' : 'R' );

					}

					const toText = vNormalize( vSub( dimline, knee ) ) || vNormalize( vSub( dimline, radius ) ) || xAxis;
					out.label = { point: dimline, dir: xAxis, align: vDot( toText, xAxis ) >= 0 ? 'left' : 'right', valign: 'middle', gap: true };
					break;

				}

				case 'Leader': {

					const points = [];
					if ( pts && typeof pts.length === 'number' ) {

						for ( let i = 0; i < pts.length; i ++ ) {

							const p = toXYZ( pts[ i ] );
							if ( p ) points.push( p );

						}

					}

					if ( points.length === 0 ) break;
					for ( let i = 0; i + 1 < points.length; i ++ ) line( points[ i ], points[ i + 1 ] );
					if ( points.length >= 2 ) {

						arrow( points[ 0 ], points[ 1 ], enumName( style && style.leaderArrowType, 'ArrowheadTypes_' ), len( style && style.leaderArrowLength, textHeight ) );

					}

					const last = points[ points.length - 1 ];
					const lastX = vDot( vSub( last, origin ), xAxis );
					const textPoint2d = parentStyle ? tryGet( () => g.getTextPoint2d( parentStyle, scale ) ) : undefined;
					let point = last;
					let align = points.length >= 2 && vDot( vSub( last, points[ points.length - 2 ] ), xAxis ) < 0 ? 'right' : 'left';
					let gap = true;

					if ( textPoint2d && textPoint2d.length >= 2 && isFinite( textPoint2d[ 0 ] ) ) {

						// Rhino's own text point already includes the landing and the text gap.
						point = vAdd( origin, vAdd( vScale( xAxis, textPoint2d[ 0 ] ), vScale( yAxis, textPoint2d[ 1 ] ) ) );
						align = textPoint2d[ 0 ] >= lastX ? 'left' : 'right';
						gap = false;
						const landing = len( style && style.leaderLandingLength, 0 );
						if ( style && style.leaderHasLanding && landing > 0 ) {

							const sign = align === 'left' ? 1 : - 1;
							line( last, vAdd( last, vScale( xAxis, sign * landing ) ) );

						}

					}

					out.label = { point, dir: xAxis, align, valign: 'middle', gap };
					break;

				}

				case 'Text': {

					const rotation = tryGet( () => g.textRotationRadians ) || 0;
					const dir = rotation ? vAdd( vScale( xAxis, Math.cos( rotation ) ), vScale( yAxis, Math.sin( rotation ) ) ) : xAxis;
					const justify = textAlignment( style );
					out.label = { point: origin, dir, align: justify.h, valign: justify.v };
					break;

				}

				default: {

					// Angular, ordinate and centre marks: Rhino's own display lines, when rhino3dm
					// can compute them for this type.
					if ( parentStyle && typeof g.getDisplayLines === 'function' ) {

						const result = tryGet( () => g.getDisplayLines( parentStyle, scale ) );
						if ( result && result.lines ) {

							for ( let i = 0; i < result.lines.size(); i ++ ) {

								const l = result.lines.get( i );
								line( toXYZ( l.from ), toXYZ( l.to ) );
								if ( typeof l.delete === 'function' ) l.delete();

							}

							result.lines.delete();
							if ( result.text_rect ) result.text_rect.delete();

						}

					}

					let point = toXYZ( pts && ( pts.textpt || pts.textPoint || pts.dimlinept ) );
					if ( ! point ) {

						const box = tryGet( () => g.getTightBoundingBox() );
						if ( box && box.min[ 0 ] <= box.max[ 0 ] ) point = vScale( vAdd( box.min, box.max ), 0.5 );
						if ( box && typeof box.delete === 'function' ) box.delete();

					}

					out.label = { point: point || origin, dir: xAxis, align: 'center', valign: 'middle' };
					break;

				}

			}

			if ( ! out.text ) out.label = null;
			return out;

		} finally {

			if ( ownStyle && typeof ownStyle.delete === 'function' ) ownStyle.delete();

		}

	}

	// Hatches: rhino3dm exposes neither the loops nor the pattern, but the hatch's own
	// opennurbs record does. Each loop is written as a version byte (0x11), an int loop type
	// (0 outer, 1 inner) and the 2D boundary curve as an embedded class record, which
	// CommonObject.decode() can read on its own.
	const TCODE_OPENNURBS_CLASS = 0x00027FFA;

	function base64ToBytes( base64 ) {

		const binary = atob( base64 );
		const bytes = new Uint8Array( binary.length );
		for ( let i = 0; i < binary.length; i ++ ) bytes[ i ] = binary.charCodeAt( i );
		return bytes;

	}

	function bytesToBase64( bytes ) {

		let binary = '';
		for ( let i = 0; i < bytes.length; i += 0x8000 ) {

			binary += String.fromCharCode.apply( null, bytes.subarray( i, i + 0x8000 ) );

		}

		return btoa( binary );

	}

	function extractHatch( g ) {

		const encoded = tryGet( () => g.encode() );
		if ( ! encoded || ! encoded.data ) return null;

		const bytes = base64ToBytes( encoded.data );
		const view = new DataView( bytes.buffer, bytes.byteOffset, bytes.byteLength );
		const plane = g.plane;
		const loops = [];

		// Start past the hatch's own class record header.
		for ( let off = 12; off + 12 <= bytes.length; off ++ ) {

			if ( view.getUint32( off, true ) !== TCODE_OPENNURBS_CLASS ) continue;
			const length = Number( view.getBigUint64( off + 4, true ) );
			if ( off + 12 + length > bytes.length ) continue;
			if ( off < 5 || bytes[ off - 5 ] !== 0x11 ) continue;

			const type = view.getInt32( off - 4, true );
			const curve = tryGet( () => rhino.CommonObject.decode( {
				version: encoded.version,
				archive3dm: encoded.archive3dm,
				opennurbs: encoded.opennurbs,
				data: bytesToBase64( bytes.subarray( off, off + 12 + length ) )
			} ) );

			if ( curve && curve instanceof rhino.Curve ) {

				const points = [];
				for ( const p of curveToPoints( curve ) ) points.push( p[ 0 ], p[ 1 ] );
				if ( points.length >= 6 ) loops.push( { outer: type !== 1, points } );

			}

			if ( curve && typeof curve.delete === 'function' ) curve.delete();
			// Never look inside a record already handled (a polycurve's own segments).
			off += 11 + length;

		}

		if ( loops.length === 0 ) return null;

		return {
			plane: {
				origin: toXYZ( plane.origin ) || [ 0, 0, 0 ],
				xAxis: vNormalize( toXYZ( plane.xAxis ) ) || [ 1, 0, 0 ],
				yAxis: vNormalize( toXYZ( plane.yAxis ) ) || [ 0, 1, 0 ]
			},
			patternIndex: tryGet( () => g.patternIndex ) || 0,
			loops
		};

	}

}

export { Rhino3dmLoader };
