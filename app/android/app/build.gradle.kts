import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing comes from android/key.properties (storeFile, storePassword,
// keyAlias, keyPassword). Without it the release build falls back to the debug
// key so `flutter build apk --release` still produces an installable APK.
val keystorePropertiesFile = rootProject.file("key.properties")
val hasReleaseKeystore = keystorePropertiesFile.exists()
val keystoreProperties = Properties().apply {
    if (hasReleaseKeystore) {
        keystorePropertiesFile.inputStream().use { load(it) }
    }
}
if (!hasReleaseKeystore) {
    logger.warn("WARNING: android/key.properties not found - the release APK will be signed with the DEBUG key.")
}

fun keystoreProperty(name: String): String =
    keystoreProperties.getProperty(name)
        ?: throw GradleException("android/key.properties is missing '$name'")

android {
    namespace = "com.styro3d.rhino_viewer"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.styro3d.rhino_viewer"
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseKeystore) {
            create("release") {
                storeFile = file(keystoreProperty("storeFile"))
                storePassword = keystoreProperty("storePassword")
                keyAlias = keystoreProperty("keyAlias")
                keyPassword = keystoreProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName(if (hasReleaseKeystore) "release" else "debug")
            // R8 and resource shrinking are deliberately OFF, and these two lines are
            // what turns them off: they are not the Flutter default restated.
            // FlutterPlugin.apply() sets isMinifyEnabled = true and isShrinkResources = true
            // on `release` unless -Pshrink is given, and nothing here gives it
            // (FlutterPlugin.kt:216-228 and FlutterPluginUtils.kt:226-233, Flutter 3.47.4;
            // the `--shrink` CLI flag is documented as having no effect at all,
            // flutter_command.dart:986-990). The plugins {} block applies FlutterPlugin
            // before this script body runs, so these assignments come last and win.
            //
            // Why: the viewer dies on the user's phone before onWebViewCreated ever fires,
            // so the Android platform view is never constructed and no exception reaches
            // Dart. Every release APK this project has ever produced was minified, which
            // makes R8 the one variable on that path never observed switched off. A
            // smaller APK is not worth an app that cannot be opened. ARCHITECTURE.md 3.6b
            // records what has to be proven before this goes back on; the keeps it will
            // need are already in proguard-rules.pro next to this file, which
            // FlutterPlugin.kt:224-227 picks up on its own once minification returns.
            //
            // Both lines are required: AGP fails the build with "Removing unused resources
            // requires unused code shrinking to be turned on" if shrinking is left on alone.
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
