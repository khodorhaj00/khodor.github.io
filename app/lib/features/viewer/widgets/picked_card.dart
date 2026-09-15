import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/theme.dart';
import '../../../core/models/model_stats.dart';

/// Details of the tapped object, anchored above the toolbar. The name row
/// with the close button stays put; the attributes scroll below it, since
/// production files carry dozens of user strings.
class PickedCard extends StatelessWidget {
  const PickedCard({
    super.key,
    required this.object,
    required this.units,
    required this.onClose,
  });

  /// Fraction of the screen height the card may take.
  static const double maxHeightFraction = 0.4;

  /// Close button hit target (WCAG minimum), padded out of the card's edge.
  static const double closeTarget = 44;

  final PickedObject object;

  /// rhino3dm unit name as reported by the viewer (see [unitSymbol]).
  final String units;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final size = object.size.map(formatLength).join(' × ');
    return ConstrainedBox(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * maxHeightFraction,
      ),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(kGap * 2, 0, kGap / 2, kGap * 1.5),
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
                      width: closeTarget,
                      height: closeTarget,
                    ),
                    tooltip: 'Dismiss',
                  ),
                ],
              ),
              Flexible(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.only(right: kGap / 2),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _Row(label: 'Type', value: object.objectType),
                      if (object.blockName.isNotEmpty)
                        _Row(label: 'Block', value: object.blockName),
                      _Row(label: 'Layer', value: object.layerName),
                      _Row(
                        label: 'Size',
                        value: withUnit(size, units),
                        mono: true,
                      ),
                      for (final entry in object.userStrings.entries)
                        _Row(label: entry.key, value: entry.value),
                    ],
                  ),
                ),
              ),
            ],
          ),
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
