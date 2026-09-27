import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/app/theme.dart';
import 'package:rhino_viewer/app/units.dart';
import 'package:rhino_viewer/core/bridge/viewer_bridge.dart';
import 'package:rhino_viewer/core/models/model_stats.dart';
import 'package:rhino_viewer/core/models/viewer_events.dart';
import 'package:rhino_viewer/features/viewer/widgets/diagnostics_sheet.dart';
import 'package:rhino_viewer/features/viewer/widgets/error_panel.dart';
import 'package:rhino_viewer/features/viewer/widgets/layers_sheet.dart';
import 'package:rhino_viewer/features/viewer/widgets/loading_overlay.dart';
import 'package:rhino_viewer/features/viewer/widgets/measure_panel.dart';
import 'package:rhino_viewer/features/viewer/widgets/meshing_banner.dart';
import 'package:rhino_viewer/features/viewer/widgets/objects_sheet.dart';
import 'package:rhino_viewer/features/viewer/widgets/picked_card.dart';
import 'package:rhino_viewer/features/viewer/widgets/stats_sheet.dart';
import 'package:rhino_viewer/features/viewer/widgets/toolbar.dart';
import 'package:rhino_viewer/features/viewer/widgets/unmeshed_banner.dart';

import 'support/fixtures.dart';

Widget host(Widget child) => MaterialApp(
  theme: buildAppTheme(),
  home: Scaffold(body: child),
);

void main() {
  final stats = ModelStats.fromJson(sampleStatsJson);

  group('ViewerToolbar', () {
    testWidgets('buttons and popups invoke the callbacks', (tester) async {
      var fit = 0;
      ViewerView? view;
      DisplayMode? mode;
      var layers = 0;
      var objects = 0;
      var measure = 0;
      bool? grid;
      Projection? projection;
      RenderQuality? quality;
      await tester.pumpWidget(
        host(
          Align(
            alignment: Alignment.bottomCenter,
            child: ViewerToolbar(
              displayMode: DisplayMode.shaded,
              projection: Projection.perspective,
              grid: true,
              onFit: () => fit++,
              onView: (v) => view = v,
              onDisplayMode: (m) => mode = m,
              onRenderQuality: (q) => quality = q,
              onLayers: () => layers++,
              onObjects: () => objects++,
              onMeasure: () => measure++,
              onGrid: (g) => grid = g,
              onProjection: (p) => projection = p,
            ),
          ),
        ),
      );
      await tester.tap(find.text('Fit'));
      await tester.tap(find.text('Layers'));
      await tester.tap(find.text('Objects'));
      await tester.tap(find.text('Caliper'));
      expect(fit, 1);
      expect(layers, 1);
      expect(objects, 1);
      expect(measure, 1);

      await tester.tap(find.text('Views'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Top'));
      await tester.pumpAndSettle();
      expect(view, ViewerView.top);

      await tester.tap(find.text('Views'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Grid'));
      await tester.pumpAndSettle();
      expect(grid, isFalse, reason: 'toggles from the current value');

      await tester.tap(find.text('Views'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Orthographic'));
      await tester.pumpAndSettle();
      expect(projection, Projection.ortho);

      await tester.tap(find.text('Display'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Wireframe'));
      await tester.pumpAndSettle();
      expect(mode, DisplayMode.wireframe);

      // Lighting belongs to the rendered mode and switches it on.
      mode = null;
      bool? lighting;
      await tester.pumpWidget(
        host(
          Align(
            alignment: Alignment.bottomCenter,
            child: ViewerToolbar(
              displayMode: DisplayMode.shaded,
              projection: Projection.perspective,
              grid: true,
              onFit: () {},
              onView: (_) {},
              onDisplayMode: (m) => mode = m,
              onRenderQuality: (q) => quality = q,
              onRenderLighting: (on) => lighting = on,
              onLayers: () {},
              onGrid: (_) {},
              onProjection: (_) {},
            ),
          ),
        ),
      );
      await tester.tap(find.text('Display'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Lighting'));
      await tester.pumpAndSettle();
      expect(lighting, isFalse, reason: 'toggles from the default, on');
      expect(mode, DisplayMode.rendered);

      // Textures & shadows also switches to the rendered mode.
      mode = null;
      await tester.tap(find.text('Display'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Textures & shadows'));
      await tester.pumpAndSettle();
      expect(quality, RenderQuality.full);
      expect(mode, DisplayMode.rendered);
    });

    testWidgets('active toggles render in the accent colour', (tester) async {
      await tester.pumpWidget(
        host(
          ViewerToolbar(
            displayMode: DisplayMode.shaded,
            projection: Projection.ortho,
            grid: false,
            measuring: true,
            onFit: () {},
            onView: (_) {},
            onDisplayMode: (_) {},
            onLayers: () {},
            onObjects: () {},
            onMeasure: () {},
            onGrid: (_) {},
            onProjection: (_) {},
          ),
        ),
      );
      Color colorOf(String label) =>
          tester.widget<Text>(find.text(label)).style!.color!;
      expect(colorOf('Views'), AppColors.accent, reason: 'orthographic');
      expect(colorOf('Caliper'), AppColors.accent);
      expect(colorOf('Objects'), AppColors.text);

      await tester.tap(find.text('Views'));
      await tester.pumpAndSettle();
      final checked = {
        for (final item in tester.widgetList<CheckedPopupMenuItem<Object>>(
          find.byWidgetPredicate((w) => w is CheckedPopupMenuItem),
        ))
          (item.child! as Text).data: item.checked,
      };
      expect(checked, {'Orthographic': true, 'Grid': false});
    });

    testWidgets('fits six buttons on a 360 dp phone', (tester) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        host(
          Align(
            alignment: Alignment.bottomCenter,
            child: ViewerToolbar(
              displayMode: DisplayMode.shaded,
              projection: Projection.perspective,
              grid: true,
              onFit: () {},
              onView: (_) {},
              onDisplayMode: (_) {},
              onLayers: () {},
              onObjects: () {},
              onMeasure: () {},
              onGrid: (_) {},
              onProjection: (_) {},
            ),
          ),
        ),
      );
      for (final label in const [
        'Fit',
        'Views',
        'Display',
        'Layers',
        'Objects',
        'Caliper',
      ]) {
        expect(find.text(label), findsOneWidget);
      }
      expect(tester.takeException(), isNull);
    });

    testWidgets('Layers gets the layers glyph, Display a shading glyph', (
      tester,
    ) async {
      await tester.pumpWidget(
        host(
          ViewerToolbar(
            displayMode: DisplayMode.shaded,
            projection: Projection.perspective,
            grid: true,
            onFit: () {},
            onView: (_) {},
            onDisplayMode: (_) {},
            onLayers: () {},
            onGrid: (_) {},
            onProjection: (_) {},
          ),
        ),
      );
      final layersCell = find.ancestor(
        of: find.text('Layers'),
        matching: find.byType(Column),
      );
      final displayCell = find.ancestor(
        of: find.text('Display'),
        matching: find.byType(Column),
      );
      expect(
        find.descendant(
          of: layersCell,
          matching: find.byIcon(Icons.layers_outlined),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(of: displayCell, matching: find.byIcon(Icons.tonality)),
        findsOneWidget,
      );
    });

    testWidgets('floating SnackBars with the page margin clear the toolbar', (
      tester,
    ) async {
      // Gesture-navigation phone: 34 px bottom inset.
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      tester.view.padding = const FakeViewPadding(bottom: 34);
      tester.view.viewPadding = const FakeViewPadding(bottom: 34);
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: Scaffold(
            body: Builder(
              builder: (context) => Stack(
                children: [
                  Positioned(
                    left: 0,
                    right: 0,
                    bottom: 0,
                    child: ColoredBox(
                      color: AppColors.surface,
                      child: SafeArea(
                        top: false,
                        child: ViewerToolbar(
                          displayMode: DisplayMode.shaded,
                          projection: Projection.perspective,
                          grid: true,
                          onFit: () {},
                          onView: (_) {},
                          onDisplayMode: (_) {},
                          onLayers: () {},
                          onGrid: (_) {},
                          onProjection: (_) {},
                        ),
                      ),
                    ),
                  ),
                  Center(
                    child: TextButton(
                      onPressed: () => ScaffoldMessenger.of(context)
                          .showSnackBar(
                            const SnackBar(
                              content: Text('Meshed 12 objects in 3.20 s'),
                              margin: kViewerSnackBarMargin,
                            ),
                          ),
                      child: const Text('go'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('go'));
      await tester.pumpAndSettle();
      // The SnackBar widget's box includes its margin; the visible part is
      // the Material inside it.
      final snack = tester.getRect(
        find
            .descendant(
              of: find.byType(SnackBar),
              matching: find.byType(Material),
            )
            .first,
      );
      final toolbar = tester.getRect(find.byType(ViewerToolbar));
      expect(toolbar.top, 640 - 34 - kViewerToolbarHeight);
      expect(snack.bottom, lessThanOrEqualTo(toolbar.top));
      expect(snack.top, greaterThan(toolbar.top - 120));
    });
  });

  group('LayersSheet', () {
    testWidgets('lists layers with counts and reports toggles', (tester) async {
      final toggles = <(int, bool)>[];
      bool? all;
      await tester.pumpWidget(
        host(
          LayersSheet(
            layers: stats.layers,
            onLayerToggled: (i, v) => toggles.add((i, v)),
            onAllToggled: (v) => all = v,
          ),
        ),
      );
      expect(find.text('Default'), findsOneWidget);
      expect(find.text('HIDDEN'), findsOneWidget);
      expect(find.text('Parts::HIDDEN'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
      final boxes = tester.widgetList<Checkbox>(find.byType(Checkbox)).toList();
      expect(boxes[0].value, isTrue);
      expect(boxes[1].value, isFalse);

      await tester.tap(find.text('HIDDEN'));
      await tester.pump();
      expect(toggles, [(1, true)]);
      expect(
        tester.widgetList<Checkbox>(find.byType(Checkbox)).last.value,
        isTrue,
      );

      await tester.tap(find.text('HIDE ALL'));
      await tester.pump();
      expect(all, isFalse);
      expect(
        tester.widgetList<Checkbox>(find.byType(Checkbox)).map((c) => c.value),
        [false, false],
      );
      expect(
        find.byType(TextField),
        findsNothing,
        reason: 'a handful of layers needs no filter',
      );
    });

    List<LayerInfo> manyLayers(int count) => [
      for (var i = 0; i < count; i++)
        LayerInfo(
          index: i,
          name: 'Layer $i',
          fullPath: i.isEven ? 'Layer $i' : 'Group::Layer $i',
          color: '#808080',
          visible: true,
          objectCount: i,
        ),
    ];

    testWidgets('filters by name or path; All/None act on the matches', (
      tester,
    ) async {
      final toggles = <(int, bool)>[];
      var allCalls = 0;
      await tester.pumpWidget(
        host(
          LayersSheet(
            layers: manyLayers(150),
            onLayerToggled: (i, v) => toggles.add((i, v)),
            onAllToggled: (_) => allCalls++,
          ),
        ),
      );
      expect(find.byType(TextField), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'layer 14');
      await tester.pump();
      expect(find.text('LAYERS · 11 OF 150'), findsOneWidget);
      expect(find.text('Layer 14'), findsOneWidget);
      expect(find.text('Layer 15'), findsNothing);

      await tester.tap(find.text('HIDE ALL'));
      await tester.pump();
      expect(allCalls, 0, reason: 'a filtered None must not hide everything');
      expect(toggles.map((t) => t.$1).toSet(), {
        14,
        for (var i = 140; i < 150; i++) i,
      });
      expect(toggles.every((t) => t.$2 == false), isTrue);
      expect(
        tester.widget<Checkbox>(find.byType(Checkbox).first).value,
        isFalse,
      );

      await tester.enterText(find.byType(TextField), 'group::layer 14');
      await tester.pump();
      expect(find.text('LAYERS · 5 OF 150'), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'nothing');
      await tester.pump();
      expect(find.text('No matching layers'), findsOneWidget);

      await tester.tap(find.byTooltip('Clear filter'));
      await tester.pump();
      expect(find.text('LAYERS'), findsOneWidget);
      toggles.clear();
      await tester.tap(find.text('ALL VIS'));
      await tester.pump();
      expect(allCalls, 1);
      expect(toggles, isEmpty);
      expect(
        tester.widget<Checkbox>(find.byType(Checkbox).first).value,
        isTrue,
      );
    });

    testWidgets('the modal sheet can be dragged to most of the screen', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        host(
          Builder(
            builder: (context) => TextButton(
              onPressed: () => LayersSheet.show(
                context,
                layers: manyLayers(150),
                onLayerToggled: (_, _) {},
                onAllToggled: (_) {},
              ),
              child: const Text('open'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      // The sheet's outermost Column starts at the sheet's top edge.
      final body = find
          .descendant(
            of: find.byType(LayersSheet),
            matching: find.byType(Column),
          )
          .first;
      expect(
        tester.getTopLeft(body).dy,
        closeTo(640 * (1 - LayersSheet.initialSize), 4),
      );
      expect(find.byType(TextField), findsOneWidget);

      await tester.drag(find.byType(ListView), const Offset(0, -400));
      await tester.pumpAndSettle();
      expect(
        tester.getTopLeft(body).dy,
        closeTo(640 * (1 - LayersSheet.maxSize), 4),
      );
      // A dimming barrier would be an AnimatedModalBarrier; a transparent
      // one keeps the model visible while layers are toggled.
      expect(find.byType(AnimatedModalBarrier), findsNothing);
    });
  });

  PickedObject pickedObject({
    Map<String, String> userStrings = const {},
    String blockName = '',
  }) => PickedObject.fromJson({
    'id': '1',
    'name': 'Bracket',
    'objectType': 'Brep',
    'blockName': blockName,
    'layerIndex': 0,
    'layerName': 'PARTS',
    'userStrings': userStrings,
    'size': [10, 20.5, 30],
    'center': [0, 0, 0],
  });

  group('ObjectsSheet', () {
    testWidgets('lists the categories in the file and reports switches', (
      tester,
    ) async {
      final shown = <(ObjectCategory, bool)>[];
      final picks = <(ObjectCategory, bool)>[];
      await tester.pumpWidget(
        host(
          ObjectsSheet(
            counts: stats.categories,
            visible: {
              for (final c in ObjectCategory.values)
                c: c != ObjectCategory.hatches,
            },
            pickable: {for (final c in ObjectCategory.values) c: true},
            onVisibleChanged: (c, v) => shown.add((c, v)),
            onPickableChanged: (c, v) => picks.add((c, v)),
          ),
        ),
      );
      expect(find.text('Annotations'), findsOneWidget);
      expect(find.text('Surfaces & solids'), findsOneWidget);
      expect(find.text('Blocks'), findsNothing, reason: 'none in the file');
      expect(find.text('218'), findsOneWidget);
      // Rows: surfaces, meshes, curves, points, annotations, hatches; each
      // with a Show and a Select box.
      Checkbox box(int i) =>
          tester.widget<Checkbox>(find.byType(Checkbox).at(i));
      expect(find.byType(Checkbox), findsNWidgets(12));
      expect(box(10).value, isFalse, reason: 'hatches start hidden here');

      await tester.tap(find.byType(Checkbox).at(8));
      await tester.pump();
      await tester.tap(find.byType(Checkbox).at(1));
      await tester.pump();
      expect(shown, [(ObjectCategory.annotations, false)]);
      expect(picks, [(ObjectCategory.surfaces, false)]);
      expect(box(8).value, isFalse);
      expect(box(1).value, isFalse);
    });

    testWidgets('lists every category when the page sent no counts', (
      tester,
    ) async {
      await tester.pumpWidget(
        host(
          ObjectsSheet(
            counts: const {},
            visible: const {},
            pickable: const {},
            onVisibleChanged: (_, _) {},
            onPickableChanged: (_, _) {},
          ),
        ),
      );
      expect(
        find.byType(Checkbox),
        findsNWidgets(ObjectCategory.values.length * 2),
      );
    });
  });

  group('MeasurePanel', () {
    testWidgets('guides the taps, then shows distance and deltas', (
      tester,
    ) async {
      var cleared = 0;
      var closed = 0;
      Future<void> pump(MeasureResult result) => tester.pumpWidget(
        host(
          MeasurePanel(
            result: result,
            lengths: const LengthFormat(
              unit: DisplayUnit.file,
              modelUnits: 'Millimeters',
            ),
            onClear: () => cleared++,
            onClose: () => closed++,
          ),
        ),
      );
      await pump(MeasureResult.empty);
      expect(find.text('Tap the first point'), findsOneWidget);
      expect(find.text('Clear'), findsNothing);

      await pump(
        const MeasureResult(
          points: [
            [0, 0, 0],
          ],
          snaps: [MeasureSnap.vertex],
        ),
      );
      expect(find.text('Tap the second point'), findsOneWidget);
      expect(find.textContaining('P1  0, 0, 0'), findsOneWidget);
      expect(find.textContaining('Vertex'), findsOneWidget);

      await pump(
        const MeasureResult(
          points: [
            [0, 0, 0],
            [-30, 40, 0],
          ],
          snaps: [MeasureSnap.vertex, MeasureSnap.surface],
          distance: 50,
          delta: [-30, 40, 0],
        ),
      );
      expect(find.text('50 mm'), findsOneWidget);
      expect(find.text('30'), findsOneWidget, reason: 'deltas are unsigned');
      expect(find.text('40'), findsOneWidget);
      expect(find.text('ΔZ'), findsOneWidget);
      await tester.tap(find.text('Clear'));
      await tester.tap(find.byTooltip('Close caliper'));
      expect(cleared, 1);
      expect(closed, 1);
    });
  });

  group('PickedCard', () {
    testWidgets('shows type, layer, size with a unit symbol and user strings', (
      tester,
    ) async {
      var closed = 0;
      await tester.pumpWidget(
        host(
          PickedCard(
            object: pickedObject(userStrings: {'material': 'EPS'}),
            lengths: const LengthFormat(
              unit: DisplayUnit.file,
              modelUnits: 'Millimeters',
            ),
            onClose: () => closed++,
          ),
        ),
      );
      expect(find.text('Bracket'), findsOneWidget);
      expect(find.text('POLYSURFACE'), findsOneWidget);
      expect(find.text('BLOCK'), findsNothing);
      expect(find.text('PARTS'), findsOneWidget);
      expect(find.text('10 mm'), findsOneWidget);
      expect(find.text('20.5 mm'), findsOneWidget);
      expect(find.text('30 mm'), findsOneWidget);
      expect(find.text('MATERIAL'), findsOneWidget);
      expect(find.text('EPS'), findsOneWidget);
      final close = tester.getSize(find.byType(IconButton));
      expect(close.width, greaterThanOrEqualTo(44));
      expect(close.height, greaterThanOrEqualTo(44));
      await tester.tap(find.byIcon(Icons.close));
      expect(closed, 1);

      await tester.pumpWidget(
        host(
          PickedCard(
            object: pickedObject(),
            lengths: const LengthFormat(
              unit: DisplayUnit.file,
              modelUnits: 'None',
            ),
            onClose: () {},
          ),
        ),
      );
      expect(find.text('20.5'), findsOneWidget);
    });

    testWidgets('names the block of a hit inside a block instance', (
      tester,
    ) async {
      await tester.pumpWidget(
        host(
          PickedCard(
            object: pickedObject(blockName: 'unit_box'),
            lengths: const LengthFormat(
              unit: DisplayUnit.file,
              modelUnits: 'Millimeters',
            ),
            onClose: () {},
          ),
        ),
      );
      expect(find.text('BLOCK'), findsOneWidget);
      expect(find.text('unit_box'), findsOneWidget);
    });

    testWidgets('shows sizes in the chosen unit', (tester) async {
      await tester.pumpWidget(
        host(
          PickedCard(
            object: pickedObject(),
            lengths: const LengthFormat(
              unit: DisplayUnit.cm,
              modelUnits: 'Millimeters',
            ),
            onClose: () {},
          ),
        ),
      );
      expect(find.text('2.0 cm'), findsOneWidget);
    });

    testWidgets("shows an annotation's kind and text", (tester) async {
      await tester.pumpWidget(
        host(
          PickedCard(
            object: PickedObject.fromJson({
              'objectType': 'Annotation',
              'subtype': 'Linear dimension',
              'text': '328.4',
              'layerName': 'DIMS',
              'size': [100, 0, 0],
            }),
            lengths: const LengthFormat(
              unit: DisplayUnit.file,
              modelUnits: 'Millimeters',
            ),
            onClose: () {},
          ),
        ),
      );
      // Title (no name) and the type badge.
      expect(find.text('Linear dimension'), findsOneWidget);
      expect(find.text('LINEAR DIMENSION'), findsOneWidget);
      expect(find.text('TEXT'), findsOneWidget);
      expect(find.text('328.4'), findsOneWidget);
    });

    testWidgets('keeps the close button on screen and scrolls many strings', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final strings = {for (var i = 0; i < 25; i++) 'key$i': 'value$i'};
      await tester.pumpWidget(
        host(
          Stack(
            children: [
              Positioned(
                left: kGap,
                right: kGap * 8,
                bottom: kViewerToolbarHeight + kGap,
                child: PickedCard(
                  object: pickedObject(userStrings: strings),
                  lengths: const LengthFormat(
                    unit: DisplayUnit.file,
                    modelUnits: 'Millimeters',
                  ),
                  onClose: () {},
                ),
              ),
            ],
          ),
        ),
      );
      final card = tester.getRect(find.byType(PickedCard));
      expect(
        card.height,
        lessThanOrEqualTo(640 * PickedCard.maxHeightFraction),
      );
      expect(card.top, greaterThanOrEqualTo(0));
      final close = tester.getRect(find.byIcon(Icons.close));
      expect(close.top, greaterThanOrEqualTo(card.top));
      expect(
        tester.getRect(find.text('value24')).top,
        greaterThan(card.bottom),
      );

      await tester.drag(
        find.byType(SingleChildScrollView),
        const Offset(0, -2000),
      );
      await tester.pumpAndSettle();
      expect(
        tester.getRect(find.text('value24')).bottom,
        lessThanOrEqualTo(card.bottom),
      );
      expect(
        tester.getRect(find.byIcon(Icons.close)),
        close,
        reason: 'the header row is pinned',
      );
    });
  });

  testWidgets('UnmeshedBanner offers the server action matching the settings', (
    tester,
  ) async {
    var meshed = 0;
    var setup = 0;
    Widget banner(bool configured) => host(
      UnmeshedBanner(
        count: 3,
        backendConfigured: configured,
        onMeshOnServer: () => meshed++,
        onSetupServer: () => setup++,
      ),
    );
    await tester.pumpWidget(banner(false));
    expect(find.text('3 objects have no render mesh'), findsOneWidget);
    expect(find.text('Set up server'), findsOneWidget);
    expect(find.text('Mesh on server'), findsNothing);
    await tester.tap(find.text('Set up server'));
    expect(setup, 1);

    await tester.pumpWidget(banner(true));
    await tester.tap(find.text('Mesh on server'));
    expect(meshed, 1);
    expect(find.textContaining('Save small'), findsOneWidget);

    // Without a server and without a setup action: the Rhino advice only.
    await tester.pumpWidget(
      host(
        UnmeshedBanner(
          count: 2,
          backendConfigured: false,
          onMeshOnServer: () => meshed++,
        ),
      ),
    );
    expect(find.byType(FilledButton), findsNothing);
    expect(find.byType(OutlinedButton), findsNothing);
    expect(
      find.text('re-save in Rhino with Save small unchecked'),
      findsOneWidget,
    );

    // Once the server-meshed copy is shown, the leftovers are what the
    // server could not mesh: no point offering the same round trip again.
    await tester.pumpWidget(
      host(
        UnmeshedBanner(
          count: 1,
          backendConfigured: true,
          serverTried: true,
          onMeshOnServer: () => meshed++,
          onSetupServer: () => setup++,
        ),
      ),
    );
    expect(
      find.text('1 object could not be meshed by the server'),
      findsOneWidget,
    );
    expect(find.text('Mesh on server'), findsNothing);
    expect(find.text('Set up server'), findsNothing);
    expect(find.textContaining('Save small'), findsOneWidget);
  });

  testWidgets('StatsSheet renders counts, units and engine versions', (
    tester,
  ) async {
    // The sheet is a lazy list sized to 60 % of the screen: use a tall
    // viewport so every row is built.
    tester.view.physicalSize = const Size(1080, 4000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      host(
        StatsSheet(
          fileName: 'logo.3dm',
          stats: stats,
          ready: const ViewerReadyInfo(three: 'r186', rhino3dm: '8.32.2'),
        ),
      ),
    );
    expect(find.text('logo.3dm'), findsOneWidget);
    expect(find.text('48,210'), findsOneWidget);
    expect(find.text('Millimeters'), findsOneWidget);
    expect(find.text('20 × 40 × 5.5 mm'), findsOneWidget);
    expect(find.text('3 (2 Brep, 1 Extrusion)'), findsOneWidget);
    expect(find.text('r186'), findsOneWidget);
    expect(find.text('8.32.2'), findsOneWidget);
    expect(find.textContaining('no mesh: Brep abc'), findsOneWidget);
  });

  testWidgets('MeshingBanner shows the phase and offers Cancel', (
    tester,
  ) async {
    var cancelled = 0;
    await tester.pumpWidget(
      host(
        MeshingBanner(
          status: 'Uploading 12.4 MB · 45 %',
          onCancel: () => cancelled++,
        ),
      ),
    );
    expect(find.text('Meshing on server'), findsOneWidget);
    expect(find.text('Uploading 12.4 MB · 45 %'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    expect(cancelled, 1);
  });

  testWidgets('LoadingOverlay shows the label and a progress bar', (
    tester,
  ) async {
    await tester.pumpWidget(
      host(
        const Stack(
          children: [LoadingOverlay(label: 'Parsing x.3dm', progress: 0.4)],
        ),
      ),
    );
    expect(find.text('Parsing x.3dm'), findsOneWidget);
    expect(
      tester
          .widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator))
          .value,
      0.4,
    );
  });

  testWidgets('LoadingOverlay names the stage, the file and the last error', (
    tester,
  ) async {
    await tester.pumpWidget(
      host(
        const Stack(
          children: [
            LoadingOverlay(
              label: 'Parsing the model',
              detail: 'KIOSK information-1.3dm',
              problem: 'Page error: WebGL is not available',
              opaque: true,
            ),
          ],
        ),
      ),
    );
    expect(find.text('Parsing the model'), findsOneWidget);
    expect(find.text('KIOSK information-1.3dm'), findsOneWidget);
    expect(find.text('Page error: WebGL is not available'), findsOneWidget);
    expect(
      tester
          .widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator))
          .value,
      isNull,
      reason: 'an unmeasured stage spins instead of claiming 0 %',
    );
    expect(
      tester.widget<ColoredBox>(_firstBox(find.byType(LoadingOverlay))).color,
      AppColors.bg,
      reason: 'an opaque overlay is what hides a blank or grey WebView',
    );
  });

  testWidgets('ViewerErrorPanel states the failure and offers a way out', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    var retry = 0;
    var diagnostics = 0;
    var back = 0;
    await tester.pumpWidget(
      host(
        Stack(
          children: [
            ViewerErrorPanel(
              message:
                  'The 3D engine did not start. Nothing happened for 20 s at '
                  '"Viewer page loaded".',
              onRetry: () => retry++,
              onDiagnostics: () => diagnostics++,
              onBack: () => back++,
            ),
          ],
        ),
      ),
    );
    expect(find.text('Could not display this file'), findsOneWidget);
    expect(find.textContaining('The 3D engine did not start'), findsOneWidget);
    expect(
      tester.widget<ColoredBox>(_firstBox(find.byType(ViewerErrorPanel))).color,
      AppColors.bg,
    );
    await tester.tap(find.text('Retry'));
    await tester.tap(find.text('Diagnostics'));
    await tester.tap(find.text('Back'));
    expect([retry, diagnostics, back], [1, 1, 1]);
    expect(
      find.text('Other rendering mode'),
      findsNothing,
      reason: 'a page that loaded is not a compositing failure',
    );
  });

  testWidgets('ViewerErrorPanel offers the other rendering mode when asked', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    var switched = 0;
    await tester.pumpWidget(
      host(
        Stack(
          children: [
            ViewerErrorPanel(
              message: 'The viewer never started.',
              onRetry: () {},
              onDiagnostics: () {},
              onBack: () {},
              onAlternateRendering: () => switched++,
            ),
          ],
        ),
      ),
    );
    await tester.tap(find.text('Other rendering mode'));
    expect(switched, 1);
  });

  testWidgets('DiagnosticsSheet waits for the page, then copies in one tap', (
    tester,
  ) async {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    final calls = <MethodCall>[];
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      calls.add(call);
      return null;
    });
    addTearDown(
      () => messenger.setMockMethodCallHandler(SystemChannels.platform, null),
    );
    final report = Completer<String>();
    await tester.pumpWidget(host(DiagnosticsSheet(report: report.future)));
    expect(find.text('Collecting…'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, 'Copy'))
          .onPressed,
      isNull,
      reason: 'nothing to copy yet',
    );

    report.complete('Rhino Viewer diagnostics\nStage     Parsing the model');
    await tester.pumpAndSettle();
    expect(find.textContaining('Stage     Parsing the model'), findsOneWidget);

    await tester.tap(find.text('Copy'));
    await tester.pumpAndSettle();
    final copied = calls.where((c) => c.method == 'Clipboard.setData');
    expect(copied, hasLength(1));
    expect(
      (copied.single.arguments as Map)['text'],
      contains('Rhino Viewer diagnostics'),
    );
    expect(find.text('Diagnostics copied'), findsOneWidget);
  });

  testWidgets('DiagnosticsSheet shows why it has nothing to show', (
    tester,
  ) async {
    // Completed after the sheet is listening: an error future nobody has
    // attached to yet is reported to the zone instead of to the builder.
    final report = Completer<String>();
    await tester.pumpWidget(host(DiagnosticsSheet(report: report.future)));
    report.completeError('no WebView is running');
    await tester.pumpAndSettle();
    expect(find.textContaining('no WebView is running'), findsOneWidget);
  });
}

/// The outermost [ColoredBox] of a widget: its backdrop.
Finder _firstBox(Finder of) =>
    find.descendant(of: of, matching: find.byType(ColoredBox)).first;
