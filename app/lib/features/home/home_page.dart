import 'package:flutter/material.dart';

import '../../app/app_services.dart';
import '../../app/format.dart';
import '../../app/stitch.dart';
import '../../app/theme.dart';
import '../../core/models/recent_file.dart';
import '../../core/services/device_info_service.dart';
import '../../core/services/file_service.dart';
import '../settings/settings_page.dart';
import '../viewer/widgets/diagnostics_sheet.dart';
import 'app_report.dart';

typedef OpenEntryCallback = Future<void> Function(
  BuildContext context,
  RecentFile entry,
);

/// File browser: the Open button, the phone's telemetry and the recent files
/// (ARCHITECTURE.md §3.4), in the Stitch look. Navigation to the viewer is
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

  /// Null until the phone answers, and on platforms without the channel.
  DeviceInfo? _device;
  bool _deviceAnswered = false;

  /// How long a swiped-away entry can be brought back before its cached
  /// file is deleted.
  static const Duration undoWindow = Duration(seconds: 5);

  /// Entries swiped away whose Undo SnackBar is still up: hidden from the
  /// list, but still in the cache until the SnackBar closes without Undo.
  final Set<String> _pendingRemoval = {};

  @override
  void initState() {
    super.initState();
    widget.services.cache.addListener(_refresh);
    _refresh();
    _readDevice();
  }

  Future<void> _readDevice() async {
    final device = await widget.services.device.read();
    if (!mounted) return;
    setState(() {
      _device = device;
      _deviceAnswered = true;
    });
  }

  void _openSettings() => Navigator.of(context)
      .push(
        MaterialPageRoute<void>(
          builder: (_) => SettingsPage(services: widget.services),
        ),
      )
      // Storage may have changed (Clear cache).
      .then((_) => _readDevice());

  void _showDiagnostics() => DiagnosticsSheet.show(
    context,
    report: buildAppReport(
      at: DateTime.now(),
      uncaught: widget.services.errors.records,
      hybridComposition:
          widget.services.settings.value.hybridWebViewComposition,
    ),
  );

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

  List<RecentFile> get _visibleRecents => [
    for (final e in _recents)
      if (!_pendingRemoval.contains(e.sha)) e,
  ];

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
  // dismissed, so the entry is hidden first; the cached file (which may be
  // the only copy the user has) is deleted only once Undo has expired.
  Future<void> _delete(RecentFile entry) async {
    setState(() => _pendingRemoval.add(entry.sha));
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    final reason = await messenger
        .showSnackBar(
          SnackBar(
            content: Text('Removed ${entry.name}'),
            action: SnackBarAction(label: 'Undo', onPressed: () {}),
            // A SnackBar with an action persists by default; the deletion
            // must commit on its own once the undo window has passed.
            persist: false,
            duration: undoWindow,
          ),
        )
        .closed;
    if (reason == SnackBarClosedReason.action) {
      if (mounted) setState(() => _pendingRemoval.remove(entry.sha));
      return;
    }
    await widget.services.cache.remove(entry.sha);
    if (mounted) setState(() => _pendingRemoval.remove(entry.sha));
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final recents = _visibleRecents;
    return Scaffold(
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            StitchHeader(
              kicker: 'Rhino Viewer',
              title: 'File browser',
              onSettings: _openSettings,
              actions: [
                // Reachable even when the viewer screen cannot draw, which is
                // when the report matters most.
                IconButton(
                  tooltip: 'Diagnostics',
                  icon: const Icon(Icons.bug_report_outlined),
                  onPressed: _showDiagnostics,
                ),
              ],
            ),
            Expanded(
              child: CustomScrollView(
                slivers: [
                  SliverPadding(
                    padding: const EdgeInsets.fromLTRB(
                      kGap * 2,
                      kGap * 2,
                      kGap * 2,
                      0,
                    ),
                    sliver: SliverList.list(
                      children: [
                        _OpenButton(busy: _busy, onPressed: _pick),
                        const Padding(
                          padding: EdgeInsets.only(top: kGap),
                          child: Text.rich(
                            TextSpan(
                              text:
                                  'Also opens from Files, WhatsApp, Drive via ',
                              children: [
                                TextSpan(
                                  text: 'Open with',
                                  style: TextStyle(fontStyle: FontStyle.italic),
                                ),
                              ],
                            ),
                            style: TextStyle(
                              color: AppColors.muted,
                              fontSize: 12,
                            ),
                          ),
                        ),
                        const SizedBox(height: kGap * 2),
                        _Telemetry(device: _device, answered: _deviceAnswered),
                        SectionHeading(
                          icon: Icons.history,
                          label: 'Recent .3dm files',
                          trailing: TechLabel(
                            _loaded ? '${recents.length}' : '',
                            size: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (!_loaded)
                    const SliverToBoxAdapter(child: SizedBox.shrink())
                  else if (recents.isEmpty)
                    const SliverFillRemaining(
                      hasScrollBody: false,
                      child: Center(
                        child: Text(
                          'No recent files',
                          style: TextStyle(color: AppColors.muted),
                        ),
                      ),
                    )
                  else
                    SliverPadding(
                      padding: const EdgeInsets.fromLTRB(
                        kGap * 2,
                        0,
                        kGap * 2,
                        kGap * 2,
                      ),
                      sliver: SliverList.separated(
                        itemCount: recents.length,
                        separatorBuilder: (_, _) =>
                            const SizedBox(height: kGap),
                        itemBuilder: (_, i) => _RecentTile(
                          entry: recents[i],
                          latest: i == 0,
                          onTap: () => _openRecent(recents[i]),
                          onDelete: () => _delete(recents[i]),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The big amber button of the design: file icon, label, arrow.
class _OpenButton extends StatelessWidget {
  const _OpenButton({required this.busy, required this.onPressed});

  final bool busy;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.accent,
      borderRadius: kRadius,
      child: InkWell(
        borderRadius: kRadius,
        onTap: busy ? null : onPressed,
        child: Padding(
          padding: const EdgeInsets.all(kGap * 1.5),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.onAccent),
                  borderRadius: kRadius,
                ),
                child: busy
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: AppColors.onAccent,
                        ),
                      )
                    : const Icon(
                        Icons.note_add_outlined,
                        color: AppColors.onAccent,
                      ),
              ),
              const SizedBox(width: kGap * 1.5),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'OPEN .3DM FILE',
                      style: TextStyle(
                        fontFamily: kTitleFamily,
                        color: AppColors.onAccent,
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    SizedBox(height: 2),
                    Text(
                      'Tap to browse the phone or a USB drive',
                      style: TextStyle(color: AppColors.onAccent, fontSize: 12),
                    ),
                  ],
                ),
              ),
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppColors.onAccent.withValues(alpha: 0.12),
                  borderRadius: kRadius,
                ),
                child: const Icon(
                  Icons.arrow_forward,
                  color: AppColors.onAccent,
                  size: 18,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// SYS TELEMETRY: what the phone really has — memory in use, free storage, the
/// OpenGL ES version the 3D view runs on — and the installed app version.
class _Telemetry extends StatelessWidget {
  const _Telemetry({required this.device, required this.answered});

  final DeviceInfo? device;
  final bool answered;

  static String _gb(int bytes) => (bytes / (1 << 30)).toStringAsFixed(1);

  @override
  Widget build(BuildContext context) {
    final device = this.device;
    final live = device != null;
    return StitchPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  color: live ? AppColors.ok : AppColors.muted,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: kGap),
              const Expanded(child: TechLabel('Sys telemetry')),
              TechLabel(
                live ? 'Live' : (answered ? 'Unavailable' : 'Reading…'),
                color: live ? AppColors.ok : AppColors.muted,
              ),
            ],
          ),
          const SizedBox(height: kGap),
          Row(
            children: [
              Expanded(
                child: StatBox(
                  label: 'Memory',
                  value: live
                      ? '${_gb(device.ramUsed)}/${_gb(device.ramTotal)} GB'
                      : '—',
                ),
              ),
              const SizedBox(width: kGap),
              Expanded(
                child: StatBox(
                  label: 'Storage free',
                  value: live ? '${_gb(device.storageFree)} GB' : '—',
                ),
              ),
              const SizedBox(width: kGap),
              Expanded(
                child: StatBox(
                  label: 'Graphics',
                  value: live && device.glEs.isNotEmpty
                      ? 'ES ${device.glEs}'
                      : '—',
                ),
              ),
            ],
          ),
          if (live) ...[
            const SizedBox(height: kGap),
            TechLabel(
              'v${device.versionName} · ${device.model} · Android ${device.android}',
              size: 10,
            ),
          ],
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
    this.latest = false,
  });

  final RecentFile entry;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  /// The most recent file gets the amber edge.
  final bool latest;

  @override
  Widget build(BuildContext context) {
    return Dismissible(
      key: ValueKey(entry.sha),
      direction: DismissDirection.endToStart,
      onDismissed: (_) => onDelete(),
      background: Container(
        decoration: const BoxDecoration(
          color: AppColors.danger,
          borderRadius: kRadius,
        ),
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: kGap * 3),
        child: const Icon(Icons.delete_outline, color: AppColors.text),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: kRadius,
          child: StitchPanel(
            accent: latest,
            child: Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: const BoxDecoration(
                    color: AppColors.inset,
                    border: Border.fromBorderSide(kBorder),
                    borderRadius: kRadius,
                  ),
                  child: const Icon(
                    Icons.view_in_ar_outlined,
                    color: AppColors.text,
                    size: 20,
                  ),
                ),
                const SizedBox(width: kGap * 1.5),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        entry.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontFamily: kTitleFamily,
                          color: latest ? AppColors.accent : AppColors.text,
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${formatBytes(entry.size)} · ${formatRelative(entry.lastOpenedAt)}',
                        style: monoNumbers.copyWith(
                          color: AppColors.muted,
                          fontSize: 12,
                        ),
                      ),
                      if (entry.meshed) ...[
                        const SizedBox(height: 4),
                        const StitchChip('Meshed'),
                      ],
                    ],
                  ),
                ),
                const Icon(Icons.chevron_right, color: AppColors.muted),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
