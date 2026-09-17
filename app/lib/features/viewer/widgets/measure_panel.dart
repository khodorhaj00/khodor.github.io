import 'package:flutter/material.dart';

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
    return Card(
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
                  child: Text(
                    'CALIPER',
                    style: TextStyle(
                      color: AppColors.accent,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 1,
                    ),
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
                  color: AppColors.text,
                  fontSize: 22,
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
                  for (final (i, axis) in const ['ΔX', 'ΔY', 'ΔZ'].indexed)
                    Expanded(
                      child: _Delta(
                        axis: axis,
                        value: lengths.bare(delta[i].abs()),
                      ),
                    ),
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

class _Delta extends StatelessWidget {
  const _Delta({required this.axis, required this.value});

  final String axis;
  final String value;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Text(axis, style: const TextStyle(color: AppColors.muted, fontSize: 11)),
      const SizedBox(width: 4),
      Flexible(
        child: Text(
          value,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: monoNumbers.copyWith(color: AppColors.text, fontSize: 13),
        ),
      ),
    ],
  );
}
