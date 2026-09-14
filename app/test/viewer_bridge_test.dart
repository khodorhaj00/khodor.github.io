import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/bridge/viewer_bridge.dart';
import 'package:rhino_viewer/core/models/viewer_events.dart';

import 'support/fixtures.dart';

class FakeJsRunner implements JsRunner {
  final List<String> sources = [];
  final Map<String, JsHandler> handlers = {};
  Object? nextResult;

  @override
  Future<dynamic> evaluateJavascript(String source) async {
    sources.add(source);
    return nextResult;
  }

  @override
  void addJavaScriptHandler(String handlerName, JsHandler callback) {
    handlers[handlerName] = callback;
  }
}

void main() {
  late FakeJsRunner runner;
  late ViewerBridge bridge;

  setUp(() {
    runner = FakeJsRunner();
    bridge = ViewerBridge(runner)..registerHandlers();
  });

  tearDown(() => bridge.dispose());

  test('registers exactly the §2.2 handlers', () {
    expect(
      runner.handlers.keys,
      unorderedEquals([
        'viewerReady',
        'loadProgress',
        'loadResult',
        'exportResult',
        'objectPicked',
        'log',
      ]),
    );
  });

  group('commands produce the §2.1 JavaScript', () {
    test('load with url', () async {
      await bridge.load(
        url: 'https://appassets.androidplatform.net/files/ab.3dm',
        name: 'my "part".3dm',
      );
      expect(
        runner.sources.single,
        'window.viewer.load({"url":"https://appassets.androidplatform.net/files/ab.3dm","name":"my \\"part\\".3dm"})',
      );
    });

    test('load with base64 omits url', () async {
      await bridge.load(base64: 'AAAA', name: 'x');
      expect(
        runner.sources.single,
        'window.viewer.load({"base64":"AAAA","name":"x"})',
      );
    });

    test('simple commands', () async {
      await bridge.clear();
      await bridge.fit();
      await bridge.setView(ViewerView.top);
      await bridge.setProjection(Projection.ortho);
      await bridge.setDisplayMode(DisplayMode.shadedEdges);
      await bridge.setLayerVisible(3, false);
      await bridge.setAllLayersVisible(true);
      await bridge.setCurvesVisible(false);
      await bridge.setPointsVisible(true);
      await bridge.setGrid(false);
      await bridge.setBackground('#1B1F26', '#0E1013');
      await bridge.exportGlb();
      expect(runner.sources, [
        'window.viewer.clear()',
        'window.viewer.fit()',
        'window.viewer.setView("top")',
        'window.viewer.setProjection("ortho")',
        'window.viewer.setDisplayMode("shaded_edges")',
        'window.viewer.setLayerVisible(3, false)',
        'window.viewer.setAllLayersVisible(true)',
        'window.viewer.setCurvesVisible(false)',
        'window.viewer.setPointsVisible(true)',
        'window.viewer.setGrid(false)',
        'window.viewer.setBackground("#1B1F26", "#0E1013")',
        'window.viewer.exportGlb()',
      ]);
    });

    test('display mode wire names cover the contract', () {
      expect(DisplayMode.values.map((m) => m.wireName), [
        'shaded',
        'shaded_edges',
        'wireframe',
        'ghosted',
      ]);
      expect(ViewerView.values.map((v) => v.name), [
        'iso',
        'top',
        'bottom',
        'front',
        'back',
        'left',
        'right',
      ]);
    });
  });

  group('getStats', () {
    test('parses the JSON string result', () async {
      runner.nextResult = jsonEncode(sampleStatsJson);
      final stats = await bridge.getStats();
      expect(runner.sources.single, 'window.viewer.getStats()');
      expect(stats?.triangles, 48210);
    });

    test('returns null for "null" and for a null result', () async {
      runner.nextResult = 'null';
      expect(await bridge.getStats(), isNull);
      runner.nextResult = null;
      expect(await bridge.getStats(), isNull);
    });

    test('accepts an already-decoded map', () async {
      runner.nextResult = sampleStatsJson;
      expect((await bridge.getStats())?.meshes, 12);
    });
  });

  group('events', () {
    test('viewerReady', () async {
      final future = bridge.onReady.first;
      runner.handlers['viewerReady']!([
        {'three': 'r186', 'rhino3dm': '8.32.2'},
      ]);
      final info = await future;
      expect(info.three, 'r186');
      expect(info.rhino3dm, '8.32.2');
    });

    test('loadProgress and loadResult', () async {
      final progress = bridge.onLoadProgress.first;
      final result = bridge.onLoadResult.first;
      runner.handlers['loadProgress']!([
        {'phase': 'build', 'progress': 0.5},
      ]);
      runner.handlers['loadResult']!([
        {'ok': true, 'name': 'a.3dm', 'stats': sampleStatsJson},
      ]);
      expect((await progress).phase, LoadPhase.build);
      expect((await progress).progress, 0.5);
      expect((await result).stats?.layers, hasLength(2));
    });

    test('objectPicked null payload clears the pick', () async {
      final events = <Object?>[];
      final sub = bridge.onObjectPicked.listen(events.add);
      runner.handlers['objectPicked']!([
        {
          'id': '1',
          'name': 'n',
          'objectType': 'Mesh',
          'layerIndex': 0,
          'layerName': 'L',
          'size': [1, 1, 1],
          'center': [0, 0, 0],
        },
      ]);
      runner.handlers['objectPicked']!([null]);
      runner.handlers['objectPicked']!([]);
      await Future<void>.delayed(Duration.zero);
      await sub.cancel();
      expect(events, hasLength(3));
      expect(events[0], isNotNull);
      expect(events[1], isNull);
      expect(events[2], isNull);
    });

    test('exportResult and log', () async {
      final export = bridge.onExportResult.first;
      final log = bridge.onLog.first;
      runner.handlers['exportResult']!([
        {'ok': false, 'error': 'empty scene'},
      ]);
      runner.handlers['log']!([
        {'level': 'warn', 'message': 'hello'},
      ]);
      expect((await export).error, 'empty scene');
      expect((await log).level, ViewerLogLevel.warn);
      expect((await log).message, 'hello');
    });
  });
}
