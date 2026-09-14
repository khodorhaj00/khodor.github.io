import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/theme.dart';

/// Shown when `stats.unmeshed.total > 0` (ARCHITECTURE.md §3.4).
class UnmeshedBanner extends StatelessWidget {
  const UnmeshedBanner({
    super.key,
    required this.count,
    required this.backendConfigured,
    required this.onMeshOnServer,
    required this.onSetupServer,
  });

  final int count;
  final bool backendConfigured;
  final VoidCallback onMeshOnServer;
  final VoidCallback onSetupServer;

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
          const Icon(
            Icons.warning_amber_rounded,
            color: AppColors.accent,
            size: 20,
          ),
          const SizedBox(width: kGap),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${formatCount(count)} object${count == 1 ? '' : 's'} have no render mesh',
                  style: const TextStyle(color: AppColors.text, fontSize: 13),
                ),
                const Text(
                  'or re-save in Rhino with Save small unchecked',
                  style: TextStyle(color: AppColors.muted, fontSize: 11),
                ),
              ],
            ),
          ),
          const SizedBox(width: kGap),
          if (backendConfigured)
            FilledButton(
              onPressed: onMeshOnServer,
              style: FilledButton.styleFrom(minimumSize: const Size(0, 36)),
              child: const Text('Mesh on server'),
            )
          else
            OutlinedButton(
              onPressed: onSetupServer,
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 36)),
              child: const Text('Set up server'),
            ),
        ],
      ),
    );
  }
}
