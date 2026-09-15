import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/theme.dart';
import '../../../app/versions.dart';
import '../../../core/models/model_stats.dart';
import '../../../core/models/viewer_events.dart';

/// "Info" sheet: counts, units, extents, timings, warnings and versions.
class StatsSheet extends StatelessWidget {
  const StatsSheet({
    super.key,
    required this.fileName,
    required this.stats,
    this.ready,
  });

  final String fileName;
  final ModelStats stats;
  final ViewerReadyInfo? ready;

  static Future<void> show(
    BuildContext context, {
    required String fileName,
    required ModelStats stats,
    ViewerReadyInfo? ready,
  }) => showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    builder: (_) => StatsSheet(fileName: fileName, stats: stats, ready: ready),
  );

  @override
  Widget build(BuildContext context) {
    final size = stats.bbox.size.map(formatLength).join(' × ');
    final t = stats.timings;
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.6,
      builder: (context, controller) => ListView(
        controller: controller,
        padding: const EdgeInsets.fromLTRB(kGap * 2, kGap, kGap * 2, kGap * 3),
        children: [
          Text(
            fileName,
            style: const TextStyle(
              color: AppColors.text,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: kGap),
          _Section('Counts'),
          _Line('Objects', formatCount(stats.objects)),
          _Line('Meshes', formatCount(stats.meshes)),
          _Line('Triangles', formatCount(stats.triangles)),
          _Line('Vertices', formatCount(stats.vertices)),
          _Line('Curves', formatCount(stats.curves)),
          _Line('Points', formatCount(stats.points)),
          _Line('Point clouds', formatCount(stats.pointClouds)),
          _Line('Blocks', formatCount(stats.blocks)),
          _Line('Lights', formatCount(stats.lights)),
          _Line('Other', formatCount(stats.other)),
          _Line('Layers', formatCount(stats.layers.length)),
          _Section('Geometry'),
          _Line('Units', stats.units),
          _Line('Extents', withUnit(size, stats.units)),
          _Line(
            'Unmeshed',
            '${stats.unmeshed.total} (${stats.unmeshed.breps} Brep, ${stats.unmeshed.extrusions} Extrusion)',
          ),
          _Section('Timings'),
          _Line('Fetch', formatMs(t.fetchMs)),
          _Line('Parse', formatMs(t.parseMs)),
          _Line('Build', formatMs(t.buildMs)),
          _Line('Total', formatMs(t.totalMs)),
          if (stats.warnings.isNotEmpty) ...[
            _Section('Warnings (${stats.warnings.length})'),
            for (final w in stats.warnings)
              Padding(
                padding: const EdgeInsets.only(bottom: kGap / 2),
                child: Text(
                  '${w.type}: ${w.message}',
                  style: const TextStyle(color: AppColors.muted, fontSize: 12),
                ),
              ),
          ],
          _Section('Engine'),
          _Line('three.js', ready?.three ?? VendoredVersions.three),
          _Line('rhino3dm', ready?.rhino3dm ?? VendoredVersions.rhino3dm),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.title);

  final String title;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: kGap * 2, bottom: kGap / 2),
    child: Text(
      title.toUpperCase(),
      style: const TextStyle(
        color: AppColors.muted,
        fontSize: 11,
        letterSpacing: 1,
      ),
    ),
  );
}

class _Line extends StatelessWidget {
  const _Line(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: AppColors.text, fontSize: 13),
          ),
        ),
        Text(
          value,
          style: monoNumbers.copyWith(color: AppColors.text, fontSize: 13),
        ),
      ],
    ),
  );
}
