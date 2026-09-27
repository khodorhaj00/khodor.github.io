import 'package:flutter/material.dart';

import '../../../app/stitch.dart';
import '../../../app/theme.dart';
import '../../../app/units.dart';
import '../../../core/models/viewer_events.dart';

/// The caliper's readout, anchored above the toolbar while measure mode is
/// on: what to tap next, the two points and what they snapped to, and the
/// distance with its X/Y/Z components in model units.
class MeasurePanel extends StatelessWidget {
  const MeasurePanel({
    super.key,
    required this.result,
    required this.lengths,
    required this.onClear,
    required this.onClose,
  });

  final MeasureResult result;

  /// Formats lengths in the unit the user chose.
  final LengthFormat lengths;
  final VoidCallback onClear;
  final VoidCallback onClose;

  String get _hint => switch (result.points.length) {
    0 => 'Tap the first point',
    1 => 'Tap the second point',
    _ => 'Tap again to start a new measurement',
  };

  @override
  Widget build(BuildContext context) {
    final distance = result.distance;
    final delta = result.delta;
    return StitchPanel(
      accent: true,
      color: AppColors.surface.withValues(alpha: 0.96),
      padding: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kGap * 2, kGap / 2, kGap / 2, kGap),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.straighten, size: 16, color: AppColors.accent),
                const SizedBox(width: kGap),
                const Expanded(
                  child: TechLabel(
                    'Caliper · point to point',
                    color: AppColors.accent,
                  ),
                ),
                if (result.points.isNotEmpty)
                  TextButton(onPressed: onClear, child: const Text('Clear')),
                IconButton(
                  onPressed: onClose,
                  icon: const Icon(Icons.close, size: 18),
                  color: AppColors.muted,
                  tooltip: 'Close caliper',
                ),
              ],
            ),
            if (distance != null)
              Text(
                lengths.format(distance),
                style: monoNumbers.copyWith(
                  color: AppColors.accent,
                  fontSize: 26,
                  fontWeight: FontWeight.w600,
                ),
              )
            else
              Text(
                _hint,
                style: const TextStyle(color: AppColors.muted, fontSize: 13),
              ),
            if (delta != null) ...[
              const SizedBox(height: kGap / 2),
              Row(
                children: [
                  for (final (i, axis) in const ['ΔX', 'ΔY', 'ΔZ'].indexed) ...[
                    if (i > 0) const SizedBox(width: kGap / 2),
                    Expanded(
                      child: StatBox(
                        label: axis,
                        value: lengths.bare(delta[i].abs()),
                      ),
                    ),
                  ],
                ],
              ),
            ],
            for (final (i, point) in result.points.indexed)
              Padding(
                padding: const EdgeInsets.only(top: kGap / 2),
                child: Text(
                  'P${i + 1}  ${lengths.formatPoint(point)}'
                  '  · ${result.snaps[i].label}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: monoNumbers.copyWith(
                    color: AppColors.muted,
                    fontSize: 11,
                  ),
                ),
              ),
            if (distance != null)
              Padding(
                padding: const EdgeInsets.only(top: kGap / 2),
                child: Text(
                  _hint,
                  style: const TextStyle(color: AppColors.muted, fontSize: 11),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
