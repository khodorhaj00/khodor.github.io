import 'package:flutter/material.dart';

import 'theme.dart';

/// What the app shows when a widget fails to build.
///
/// Flutter's own replacement for a broken widget renders a featureless box in
/// a release build: no message, no hint that anything failed. A screen whose
/// body throws therefore looks exactly like a screen that drew nothing, which
/// is indistinguishable from a dead platform view or a blank web page and
/// sends a bug hunt down the wrong path. This shows the error instead.
///
/// It must survive being built in place of anything, so it depends on no
/// inherited widget: no Theme, no Directionality, no Material, no
/// MediaQuery. Everything it needs is literal.
class BuildFailureScreen extends StatelessWidget {
  const BuildFailureScreen({super.key, required this.details});

  final FlutterErrorDetails details;

  /// Installs this as the replacement for any widget that fails to build.
  static void install() {
    ErrorWidget.builder = (details) => BuildFailureScreen(details: details);
  }

  @override
  Widget build(BuildContext context) {
    final summary = details.exceptionAsString();
    final where = details.context?.toDescription();
    return Directionality(
      textDirection: TextDirection.ltr,
      child: ColoredBox(
        color: AppColors.bg,
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    'This screen could not be drawn',
                    style: TextStyle(
                      color: AppColors.text,
                      fontSize: 18,
                      fontWeight: FontWeight.w600,
                      decoration: TextDecoration.none,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Go back and open Diagnostics to copy this, then send it '
                    'to support.',
                    style: TextStyle(
                      color: AppColors.muted,
                      fontSize: 14,
                      decoration: TextDecoration.none,
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (where != null && where.isNotEmpty) ...[
                    Text(
                      'While $where',
                      style: const TextStyle(
                        color: AppColors.muted,
                        fontSize: 12,
                        fontFamily: 'monospace',
                        decoration: TextDecoration.none,
                      ),
                    ),
                    const SizedBox(height: 8),
                  ],
                  Text(
                    summary,
                    style: const TextStyle(
                      color: AppColors.danger,
                      fontSize: 13,
                      height: 1.5,
                      fontFamily: 'monospace',
                      decoration: TextDecoration.none,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
