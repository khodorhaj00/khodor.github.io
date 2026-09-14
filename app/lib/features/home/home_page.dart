import 'package:flutter/material.dart';

import '../../app/app_services.dart';
import '../../app/format.dart';
import '../../app/theme.dart';
import '../../core/models/recent_file.dart';
import '../../core/services/file_service.dart';
import '../settings/settings_page.dart';

typedef OpenEntryCallback = Future<void> Function(
  BuildContext context,
  RecentFile entry,
);

/// Open button + recents (ARCHITECTURE.md §3.4). Navigation to the viewer is
/// injected so the page can be widget-tested without a WebView.
class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.services, required this.onOpen});

  final AppServices services;
  final OpenEntryCallback onOpen;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  List<RecentFile> _recents = const [];
  bool _loaded = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    widget.services.cache.addListener(_refresh);
    _refresh();
  }

  @override
  void dispose() {
    widget.services.cache.removeListener(_refresh);
    super.dispose();
  }

  Future<void> _refresh() async {
    final recents = await widget.services.cache.recents();
    if (!mounted) return;
    setState(() {
      _recents = recents;
      _loaded = true;
    });
  }

  Future<void> _pick() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final imported = await widget.services.files.pickAndImport();
      if (imported == null || !mounted) return;
      final entry = await widget.services.cache.recordOpen(
        sha: imported.sha,
        name: imported.name,
        size: imported.size,
      );
      if (!mounted) return;
      await widget.onOpen(context, entry);
    } on InvalidModelFileException catch (e) {
      _snack(e.message);
    } catch (e) {
      _snack('Could not open file: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openRecent(RecentFile entry) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final files = widget.services.files;
      if (!await files.originalFile(entry.sha).exists()) {
        await widget.services.cache.remove(entry.sha);
        _snack('${entry.name} is no longer cached');
        return;
      }
      final touched = await widget.services.cache.recordOpen(
        sha: entry.sha,
        name: entry.name,
        size: entry.size,
      );
      if (!mounted) return;
      await widget.onOpen(context, touched);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // Dismissible requires its row to leave the tree as soon as it is
  // dismissed, so the list is updated before the files are deleted.
  Future<void> _delete(RecentFile entry) async {
    setState(() {
      _recents = [
        for (final e in _recents)
          if (e.sha != entry.sha) e,
      ];
    });
    await widget.services.cache.remove(entry.sha);
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Rhino Viewer'),
        actions: [
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => SettingsPage(services: widget.services),
              ),
            ),
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              kGap * 2,
              kGap * 2,
              kGap * 2,
              kGap,
            ),
            child: FilledButton.icon(
              onPressed: _busy ? null : _pick,
              icon: _busy
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppColors.onAccent,
                      ),
                    )
                  : const Icon(Icons.folder_open),
              label: const Text('Open .3dm'),
              style: FilledButton.styleFrom(minimumSize: const Size(0, 56)),
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: kGap * 2),
            child: Text.rich(
              TextSpan(
                text: 'Also opens from Files, WhatsApp, Drive via ',
                children: [
                  TextSpan(
                    text: 'Open with',
                    style: TextStyle(fontStyle: FontStyle.italic),
                  ),
                ],
              ),
              style: TextStyle(color: AppColors.muted, fontSize: 12),
            ),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(kGap * 2, kGap * 3, kGap * 2, kGap),
            child: Text(
              'RECENT',
              style: TextStyle(
                color: AppColors.muted,
                fontSize: 11,
                letterSpacing: 1,
              ),
            ),
          ),
          Expanded(
            child: !_loaded
                ? const SizedBox.shrink()
                : _recents.isEmpty
                ? const Center(
                    child: Text(
                      'No recent files',
                      style: TextStyle(color: AppColors.muted),
                    ),
                  )
                : ListView.separated(
                    itemCount: _recents.length,
                    separatorBuilder: (_, _) => const Divider(),
                    itemBuilder: (_, i) => _RecentTile(
                      entry: _recents[i],
                      onTap: () => _openRecent(_recents[i]),
                      onDelete: () => _delete(_recents[i]),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _RecentTile extends StatelessWidget {
  const _RecentTile({
    required this.entry,
    required this.onTap,
    required this.onDelete,
  });

  final RecentFile entry;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Dismissible(
      key: ValueKey(entry.sha),
      direction: DismissDirection.endToStart,
      onDismissed: (_) => onDelete(),
      background: Container(
        color: AppColors.danger,
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: kGap * 3),
        child: const Icon(Icons.delete_outline, color: AppColors.text),
      ),
      child: ListTile(
        onTap: onTap,
        leading: const Icon(Icons.view_in_ar_outlined),
        title: Text(entry.name, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text(
          '${formatBytes(entry.size)} · ${formatRelative(entry.lastOpenedAt)}',
          style: monoNumbers.copyWith(color: AppColors.muted, fontSize: 12),
        ),
        trailing: entry.meshed ? const _Badge('MESHED') : null,
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
    decoration: const BoxDecoration(
      border: Border.fromBorderSide(BorderSide(color: AppColors.accent)),
      borderRadius: kRadius,
    ),
    child: Text(
      text,
      style: const TextStyle(
        color: AppColors.accent,
        fontSize: 10,
        letterSpacing: 1,
      ),
    ),
  );
}
