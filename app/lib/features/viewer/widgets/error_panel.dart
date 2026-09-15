import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// Full-screen dead end: what failed, what to do about it, and a way to hand
/// the details to support. Opaque, because whatever is behind it is either
/// nothing or a broken page.
class ViewerErrorPanel extends StatelessWidget {
  const ViewerErrorPanel({
    super.key,
    required this.message,
    required this.onRetry,
    required this.onDiagnostics,
    required this.onBack,
    this.onAlternateRendering,
  });

  final String message;
  final VoidCallback onRetry;
  final VoidCallback onDiagnostics;
  final VoidCallback onBack;

  /// Offered only when the WebView itself never came up, which is the one
  /// failure the other composition mode can plausibly change. Null otherwise,
  /// so a file that simply could not be parsed does not suggest it.
  final VoidCallback? onAlternateRendering;

  @override
  Widget build(BuildContext context) {
    return Positioned.fill(
      child: ColoredBox(
        color: AppColors.bg,
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(kGap * 2),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(kGap * 2),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 360),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Could not display this file',
                        style: TextStyle(
                          color: AppColors.danger,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: kGap),
                      Text(
                        message,
                        style: const TextStyle(
                          color: AppColors.text,
                          fontSize: 13,
                        ),
                      ),
                      const SizedBox(height: kGap * 2),
                      Wrap(
                        alignment: WrapAlignment.end,
                        spacing: kGap,
                        runSpacing: kGap,
                        children: [
                          OutlinedButton(
                            onPressed: onBack,
                            child: const Text('Back'),
                          ),
                          OutlinedButton(
                            onPressed: onDiagnostics,
                            child: const Text('Diagnostics'),
                          ),
                          if (onAlternateRendering != null)
                            OutlinedButton(
                              onPressed: onAlternateRendering,
                              child: const Text('Other rendering mode'),
                            ),
                          FilledButton(
                            onPressed: onRetry,
                            style: FilledButton.styleFrom(
                              minimumSize: const Size(0, 40),
                            ),
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
