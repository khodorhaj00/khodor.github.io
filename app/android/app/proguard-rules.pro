# INERT TODAY. buildTypes.release sets isMinifyEnabled = false, so R8 does not run and
# nothing here has any effect. The file exists so that re-enabling minification is a
# one-line flip rather than a research project: FlutterPlugin.kt:224-227 (Flutter 3.47.4)
# adds `<module>/proguard-rules.pro` to the release proguardFiles automatically whenever
# it enables minification, so this is picked up with no wiring.
#
# Read build.gradle.kts for why minification is off and what must be proven first.

# flutter_inappwebview's platform-view factory is reached only from
# GeneratedPluginRegistrant, which swallows any exception thrown while a plugin registers
# (one Log.e line, then the app continues with the view type unregistered), so a class R8
# removed or renamed here fails silently and looks exactly like the bug this app just had.
# flutter_inappwebview_android 1.1.3 ships these same rules as consumer rules
# (android/build.gradle:36 `consumerProguardFiles 'proguard-rules.pro'`); they are repeated
# here so the keep is this module's own guarantee rather than a transitive dependency's.
-keep class com.pichillilorenzo.flutter_inappwebview_android.** { *; }

# The page calls into Dart through methods the WebView resolves by name at runtime, so
# neither the annotation nor the annotated methods may be renamed or dropped.
-keepattributes *JavascriptInterface*
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
