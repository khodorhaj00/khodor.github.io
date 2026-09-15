pluginManagement {
    val flutterSdkPath =
        run {
            val properties = java.util.Properties()
            file("local.properties").inputStream().use { properties.load(it) }
            val flutterSdkPath = properties.getProperty("flutter.sdk")
            require(flutterSdkPath != null) { "flutter.sdk not set in local.properties" }
            flutterSdkPath
        }

    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")

    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    // AGP is deliberately held on the 8.x line. AGP 9 removed support for
    // getDefaultProguardFile('proguard-android.txt'), which flutter_inappwebview_android
    // 1.1.3 still calls in its own build.gradle, so every release build fails while
    // evaluating that project. Only the plugin's 1.2.0-beta line fixes it, and that beta
    // rewrites 75 files of the WebView implementation this app is built on. Flutter 3.47
    // supports AGP down to 8.11.1, so this stays within the supported range.
    // Revisit once flutter_inappwebview ships a stable AGP 9 compatible release.
    id("com.android.application") version "8.11.1" apply false
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
}

include(":app")
