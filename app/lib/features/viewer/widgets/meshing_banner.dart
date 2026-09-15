import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// Takes the place of [UnmeshedBanner] while `/mesh` is in flight: the phase
/// text and a Cancel button, leaving the model usable underneath.
class MeshingBanner extends StatelessWidget {
  const MeshingBanner({
    super.key,
    required this.status,
    required this.onCancel,
  });

  final String status;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(kGap * 2, kGap, kGap, kGap),
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border.fromBorderSide(kBorder),
        borderRadius: kRadius,
      ),
      child: Row(
        children: [
          const SizedBox.square(
            dimension: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: kGap),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Meshing on server',
                  style: TextStyle(color: AppColors.text, fontSize: 13),
                ),
                Text(
                  status,
                  style: monoNumbers.copyWith(
                    color: AppColors.muted,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: kGap),
          OutlinedButton(
            onPressed: onCancel,
            style: OutlinedButton.styleFrom(minimumSize: const Size(0, 36)),
            child: const Text('Cancel'),
          ),
        ],
      ),
    );
  }
}
