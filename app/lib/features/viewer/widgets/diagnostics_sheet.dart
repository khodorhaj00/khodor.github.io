import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../app/theme.dart';

/// "Diagnostics" from the viewer's overflow menu: the page's own report plus
/// the app-side facts, as one block that copies to the clipboard in a tap so
/// a user can paste it to support.
class DiagnosticsSheet extends StatelessWidget {
  const DiagnosticsSheet({super.key, required this.report});

  /// Resolves once the page has answered (or failed to); the sheet opens
  /// immediately either way, so a page that never answers cannot block the
  /// menu.
  final Future<String> report;

  static const double initialSize = 0.7;

  static Future<void> show(
    BuildContext context, {
    required Future<String> report,
  }) => showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    builder: (_) => DiagnosticsSheet(report: report),
  );

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: initialSize,
      builder: (context, controller) => FutureBuilder<String>(
        future: report,
        builder: (context, snapshot) {
          final text = snapshot.hasError
              ? 'Diagnostics could not be collected: ${snapshot.error}'
              : snapshot.data;
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(kGap * 2, kGap, kGap, kGap),
                child: Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'Diagnostics',
                        style: TextStyle(
                          color: AppColors.text,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    FilledButton.icon(
                      onPressed: text == null
                          ? null
                          : () => _copy(context, text),
                      icon: const Icon(Icons.copy_all, size: 18),
                      label: const Text('Copy'),
                      style: FilledButton.styleFrom(
                        minimumSize: const Size(0, 40),
                      ),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView(
                  controller: controller,
                  padding: const EdgeInsets.fromLTRB(
                    kGap * 2,
                    kGap,
                    kGap * 2,
                    kGap * 3,
                  ),
                  children: [
                    SelectableText(
                      text ?? 'Collecting…',
                      style: monoNumbers.copyWith(
                        color: AppColors.text,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _copy(BuildContext context, String text) async {
    final messenger = ScaffoldMessenger.of(context);
    await Clipboard.setData(ClipboardData(text: text));
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(content: Text('Diagnostics copied')));
  }
}
