import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/app/theme.dart';
import 'package:rhino_viewer/core/bridge/viewer_bridge.dart';
import 'package:rhino_viewer/core/models/model_stats.dart';
import 'package:rhino_viewer/core/models/viewer_events.dart';
import 'package:rhino_viewer/features/viewer/widgets/layers_sheet.dart';
import 'package:rhino_viewer/features/viewer/widgets/loading_overlay.dart';
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
    });
  });

  testWidgets('PickedCard shows type, layer, size in units and user strings', (
    tester,
  ) async {
    var closed = 0;
    final picked = PickedObject.fromJson({
      'id': '1',
      'name': 'Bracket',
      'objectType': 'Brep',
      'layerIndex': 0,
      'layerName': 'PARTS',
      'userStrings': {'material': 'EPS'},
      'size': [10, 20.5, 30],
      'center': [0, 0, 0],
    });
    await tester.pumpWidget(
      host(PickedCard(object: picked, units: 'mm', onClose: () => closed++)),
    );
    expect(find.text('Bracket'), findsOneWidget);
    expect(find.text('Brep'), findsOneWidget);
    expect(find.text('PARTS'), findsOneWidget);
    expect(find.text('10 × 20.5 × 30 mm'), findsOneWidget);
    expect(find.text('material'), findsOneWidget);
    expect(find.text('EPS'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.close));
    expect(closed, 1);
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
    expect(find.text('20 × 40 × 5.5 Millimeters'), findsOneWidget);
    expect(find.text('3 (2 Brep, 1 Extrusion)'), findsOneWidget);
    expect(find.text('r186'), findsOneWidget);
    expect(find.text('8.32.2'), findsOneWidget);
    expect(find.textContaining('no mesh: Brep abc'), findsOneWidget);
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
}
