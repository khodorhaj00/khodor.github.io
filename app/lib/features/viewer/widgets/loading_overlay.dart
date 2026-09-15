import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// Covers the viewer with the stage it reached and a determinate bar when
/// [progress] is known, indeterminate otherwise. [opaque] hides the WebView
/// entirely, which is what keeps a page that painted nothing (or painted a
/// flat grey) from ever being visible.
class LoadingOverlay extends StatelessWidget {
  const LoadingOverlay({
    super.key,
    required this.label,
    this.detail,
    this.problem,
    this.progress,
    this.opaque = false,
  });

  /// Width of the card's content; the bar and both texts share it.
  static const double contentWidth = 240;

  final String label;

  /// Second line: which file, or what the stage is working on.
  final String? detail;

  /// Last error reported by the page or the WebView, so a failure that is not
  /// fatal by itself still reaches the user as readable text.
  final String? problem;
  final double? progress;
  final bool opaque;

  @override
  Widget build(BuildContext context) {
    final detail = this.detail;
    final problem = this.problem;
    return Positioned.fill(
      child: ColoredBox(
        color: opaque ? AppColors.bg : AppColors.bg.withValues(alpha: 0.7),
        child: Center(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(kGap * 2),
              child: SizedBox(
                width: contentWidth,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: const TextStyle(color: AppColors.text)),
                    if (detail != null) ...[
                      const SizedBox(height: kGap / 2),
                      Text(
                        detail,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.muted,
                          fontSize: 12,
                        ),
                      ),
                    ],
                    const SizedBox(height: kGap),
                    LinearProgressIndicator(value: progress, minHeight: 4),
                    if (problem != null) ...[
                      const SizedBox(height: kGap),
                      Text(
                        problem,
                        maxLines: 4,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.danger,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
