import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// Dims the viewer and shows a phase label with a determinate bar when
/// [progress] is known, indeterminate otherwise.
class LoadingOverlay extends StatelessWidget {
  const LoadingOverlay({super.key, required this.label, this.progress});

  final String label;
  final double? progress;

  @override
  Widget build(BuildContext context) {
    return Positioned.fill(
      child: ColoredBox(
        color: AppColors.bg.withValues(alpha: 0.7),
        child: Center(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(kGap * 2),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: const TextStyle(color: AppColors.text)),
                  const SizedBox(height: kGap),
                  SizedBox(
                    width: 240,
                    child: LinearProgressIndicator(
                      value: progress,
                      minHeight: 4,
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
