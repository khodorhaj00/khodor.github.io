import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/theme.dart';

/// Shown when `stats.unmeshed.total > 0` (ARCHITECTURE.md §3.4).
class UnmeshedBanner extends StatelessWidget {
  const UnmeshedBanner({
    super.key,
    required this.count,
    required this.backendConfigured,
    this.serverTried = false,
    required this.onMeshOnServer,
    this.onSetupServer,
  });

  final int count;
  final bool backendConfigured;

  /// True when the server-meshed copy is what is on screen: what is left
  /// unmeshed is what the server could not mesh, so the same round trip is
  /// not offered again.
  final bool serverTried;
  final VoidCallback onMeshOnServer;

  /// Offers "Set up server" when there is no server yet; null leaves the
  /// banner with the Rhino advice only (server meshing is optional and needs
  /// a network).
  final VoidCallback? onSetupServer;

  @override
  Widget build(BuildContext context) {
    final setup = onSetupServer;
    final serverAction = !serverTried && (backendConfigured || setup != null);
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
                  serverTried
                      ? '${formatCount(count)} object${count == 1 ? '' : 's'} could not be meshed by the server'
                      : '${formatCount(count)} object${count == 1 ? '' : 's'} have no render mesh',
                  style: const TextStyle(color: AppColors.text, fontSize: 13),
                ),
                Text(
                  serverAction
                      ? 'or re-save in Rhino with Save small unchecked'
                      : 're-save in Rhino with Save small unchecked',
                  style: const TextStyle(color: AppColors.muted, fontSize: 11),
                ),
              ],
            ),
          ),
          const SizedBox(width: kGap),
          if (!serverAction)
            const SizedBox.shrink()
          else if (backendConfigured)
            FilledButton(
              onPressed: onMeshOnServer,
              style: FilledButton.styleFrom(minimumSize: const Size(0, 36)),
              child: const Text('Mesh on server'),
            )
          else if (setup != null)
            OutlinedButton(
              onPressed: setup,
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 36)),
              child: const Text('Set up server'),
            ),
        ],
      ),
    );
  }
}
