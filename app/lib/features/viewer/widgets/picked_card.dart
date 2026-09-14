import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/theme.dart';
import '../../../core/models/model_stats.dart';

/// Details of the tapped object, anchored above the toolbar.
class PickedCard extends StatelessWidget {
  const PickedCard({
    super.key,
    required this.object,
    required this.units,
    required this.onClose,
  });

  final PickedObject object;
  final String units;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final size = object.size.map(formatLength).join(' × ');
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kGap * 2, kGap, kGap, kGap * 1.5),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    object.displayName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.text,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                IconButton(
                  onPressed: onClose,
                  icon: const Icon(Icons.close, size: 18),
                  color: AppColors.muted,
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints.tightFor(
                    width: 32,
                    height: 32,
                  ),
                  tooltip: 'Dismiss',
                ),
              ],
            ),
            _Row(label: 'Type', value: object.objectType),
            _Row(label: 'Layer', value: object.layerName),
            _Row(label: 'Size', value: '$size $units', mono: true),
            for (final entry in object.userStrings.entries)
              _Row(label: entry.key, value: entry.value),
          ],
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.label, required this.value, this.mono = false});

  final String label;
  final String value;
  final bool mono;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: kGap / 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 64,
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.muted, fontSize: 12),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: (mono ? monoNumbers : const TextStyle()).copyWith(
                color: AppColors.text,
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
