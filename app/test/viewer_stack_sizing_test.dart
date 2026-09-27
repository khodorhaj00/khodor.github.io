import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Guards the layout rule that made the viewer screen disappear.
///
/// The viewer builds a Stack whose children are all positioned: the WebView
/// fills it, and the top bar, picked card, toolbar and overlay are placed
/// against its edges. A Stack takes its size from its NON-positioned children
/// and only falls back to the incoming constraints when it has none
/// (`RenderStack._computeSize` in rendering/stack.dart). While a model was
/// loading, the overlay contributed a `Positioned.fill`, so the Stack had no
/// unpositioned child and filled the screen. The moment the model appeared the
/// overlay became a bare `SizedBox.shrink()` — the only unpositioned child —
/// and the Stack collapsed to zero, clipping the whole screen away and leaving
/// nothing but the Scaffold's background colour. No exception, no error, no
/// toolbar: a model that had loaded perfectly looked like a dead screen.
void main() {
  /// The viewer's shape: every child positioned, plus whatever the overlay
  /// contributes in its `none` state.
  Widget page({required StackFit fit, required Widget overlay}) => MaterialApp(
    home: Scaffold(
      backgroundColor: const Color(0xFF0E1013),
      body: Stack(
        key: const Key('viewer-stack'),
        fit: fit,
        children: [
          const Positioned.fill(child: ColoredBox(color: Color(0xFF101418))),
          const Positioned(
            left: 0,
            right: 0,
            top: 0,
            child: SizedBox(height: 56, key: Key('top-bar')),
          ),
          const Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: SizedBox(height: 64, key: Key('toolbar')),
          ),
          overlay,
        ],
      ),
    ),
  );

  testWidgets('an unpositioned empty overlay collapses a loose Stack', (
    tester,
  ) async {
    await tester.pumpWidget(
      page(fit: StackFit.loose, overlay: const SizedBox.shrink()),
    );

    // This is the bug, reproduced: the Stack sizes itself to its only
    // unpositioned child. The toolbar still lays out at its own height, but
    // the Stack occupies nothing, so everything inside it is clipped away and
    // the screen shows only the Scaffold's background colour.
    expect(tester.getSize(find.byKey(const Key('viewer-stack'))), Size.zero);
  });

  testWidgets('StackFit.expand keeps the screen whatever the overlay is', (
    tester,
  ) async {
    final screen = tester.view.physicalSize / tester.view.devicePixelRatio;

    for (final overlay in <Widget>[
      const SizedBox.shrink(),
      const Positioned.fill(child: IgnorePointer(child: SizedBox.shrink())),
      const Positioned.fill(child: ColoredBox(color: Color(0xFF0E1013))),
    ]) {
      await tester.pumpWidget(page(fit: StackFit.expand, overlay: overlay));

      expect(
        tester.getSize(find.byKey(const Key('viewer-stack'))).width,
        screen.width,
      );
      expect(tester.getSize(find.byKey(const Key('top-bar'))).height, 56);
      expect(tester.getSize(find.byKey(const Key('toolbar'))).height, 64);
    }
  });
}
