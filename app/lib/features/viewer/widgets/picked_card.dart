import 'package:flutter/material.dart';

import '../../../app/stitch.dart';
import '../../../app/theme.dart';
import '../../../app/units.dart';
import '../../../core/models/model_stats.dart';

/// The part card: details of the tapped object, anchored above the toolbar —
/// PART and its name, the type badge, X / Y / Z size boxes, then the rest.
/// The name row
/// with the close button stays put; the attributes scroll below it, since
/// production files carry dozens of user strings.
class PickedCard extends StatelessWidget {
  const PickedCard({
    super.key,
    required this.object,
    required this.lengths,
    required this.onClose,
  });

  /// Fraction of the screen height the card may take.
  static const double maxHeightFraction = 0.4;

  /// Close button hit target (WCAG minimum), padded out of the card's edge.
  static const double closeTarget = 44;

  final PickedObject object;

  /// Formats lengths in the unit the user chose.
  final LengthFormat lengths;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * maxHeightFraction,
      ),
      child: StitchPanel(
        accent: true,
        color: AppColors.surface.withValues(alpha: 0.96),
        padding: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            kGap * 1.5,
            0,
            kGap / 2,
            kGap * 1.5,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const TechLabel('Part', size: 10),
                        Text(
                          object.displayName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontFamily: kTitleFamily,
                            color: AppColors.text,
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
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
                      Wrap(
                        spacing: kGap,
                        runSpacing: kGap / 2,
                        children: [StitchChip(object.typeLabel, filled: true)],
                      ),
                      const SizedBox(height: kGap),
                      Row(
                        children: [
                          for (final (i, axis) in const [
                            'X',
                            'Y',
                            'Z',
                          ].indexed) ...[
                            if (i > 0) const SizedBox(width: kGap / 2),
                            Expanded(
                              child: StatBox(
                                label: axis,
                                value: lengths.format(object.size[i]),
                              ),
                            ),
                          ],
                        ],
                      ),
                      if (object.text.isNotEmpty)
                        _Row(label: 'Text', value: object.text),
                      if (object.blockName.isNotEmpty)
                        _Row(label: 'Block', value: object.blockName),
                      _Row(label: 'Layer', value: object.layerName),
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
  const _Row({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: kGap / 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 64, child: TechLabel(label, size: 10)),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(color: AppColors.text, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}
