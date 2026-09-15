import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/app/theme.dart';
import 'package:rhino_viewer/core/bridge/viewer_bridge.dart';
import 'package:rhino_viewer/core/models/model_stats.dart';
import 'package:rhino_viewer/core/models/viewer_events.dart';
import 'package:rhino_viewer/features/viewer/widgets/diagnostics_sheet.dart';
import 'package:rhino_viewer/features/viewer/widgets/error_panel.dart';
import 'package:rhino_viewer/features/viewer/widgets/layers_sheet.dart';
import 'package:rhino_viewer/features/viewer/widgets/loading_overlay.dart';
import 'package:rhino_viewer/features/viewer/widgets/meshing_banner.dart';
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
      bool? grid;
      Projection? projection;
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
              onLayers: () => layers++,
              onGrid: (g) => grid = g,
              onProjection: (p) => projection = p,
            ),
          ),
        ),
      );
      await tester.tap(find.text('Fit'));
      await tester.tap(find.text('Layers'));
      await tester.tap(find.text('Grid'));
      await tester.tap(find.text('Ortho'));
      expect(fit, 1);
      expect(layers, 1);
      expect(grid, isFalse, reason: 'toggles from the current value');
      expect(projection, Projection.ortho);

      await tester.tap(find.text('Views'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Top'));
      await tester.pumpAndSettle();
      expect(view, ViewerView.top);

      await tester.tap(find.text('Display'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Wireframe'));
      await tester.pumpAndSettle();
      expect(mode, DisplayMode.wireframe);
    });

    testWidgets('active toggles render in the accent colour', (tester) async {
      await tester.pumpWidget(
        host(
          ViewerToolbar(
            displayMode: DisplayMode.shaded,
            projection: Projection.ortho,
            grid: false,
            onFit: () {},
            onView: (_) {},
            onDisplayMode: (_) {},
            onLayers: () {},
            onGrid: (_) {},
            onProjection: (_) {},
          ),
        ),
      );
      Color colorOf(String label) =>
          tester.widget<Text>(find.text(label)).style!.color!;
      expect(colorOf('Ortho'), AppColors.accent);
      expect(colorOf('Grid'), AppColors.text);
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

      await tester.tap(find.text('None'));
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
      expect(find.text('Layers · 11 of 150'), findsOneWidget);
      expect(find.text('Layer 14'), findsOneWidget);
      expect(find.text('Layer 15'), findsNothing);

      await tester.tap(find.text('None'));
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
      expect(find.text('Layers · 5 of 150'), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'nothing');
      await tester.pump();
      expect(find.text('No matching layers'), findsOneWidget);

      await tester.tap(find.byTooltip('Clear filter'));
      await tester.pump();
      expect(find.text('Layers'), findsOneWidget);
      toggles.clear();
      await tester.tap(find.text('All'));
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

  group('PickedCard', () {
    testWidgets('shows type, layer, size with a unit symbol and user strings', (
      tester,
    ) async {
      var closed = 0;
      await tester.pumpWidget(
        host(
          PickedCard(
            object: pickedObject(userStrings: {'material': 'EPS'}),
            units: 'Millimeters',
            onClose: () => closed++,
          ),
        ),
      );
      expect(find.text('Bracket'), findsOneWidget);
      expect(find.text('Brep'), findsOneWidget);
      expect(find.text('Block'), findsNothing);
      expect(find.text('PARTS'), findsOneWidget);
      expect(find.text('10 × 20.5 × 30 mm'), findsOneWidget);
      expect(find.text('material'), findsOneWidget);
      expect(find.text('EPS'), findsOneWidget);
      final close = tester.getSize(find.byType(IconButton));
      expect(close.width, greaterThanOrEqualTo(44));
      expect(close.height, greaterThanOrEqualTo(44));
      await tester.tap(find.byIcon(Icons.close));
      expect(closed, 1);

      await tester.pumpWidget(
        host(PickedCard(object: pickedObject(), units: 'None', onClose: () {})),
      );
      expect(find.text('10 × 20.5 × 30'), findsOneWidget);
    });

    testWidgets('names the block of a hit inside a block instance', (
      tester,
    ) async {
      await tester.pumpWidget(
        host(
          PickedCard(
            object: pickedObject(blockName: 'unit_box'),
            units: 'Millimeters',
            onClose: () {},
          ),
        ),
      );
      expect(find.text('Block'), findsOneWidget);
      expect(find.text('unit_box'), findsOneWidget);
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
                  units: 'Millimeters',
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
