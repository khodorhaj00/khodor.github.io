import 'package:flutter/material.dart';

import '../../app/app_services.dart';
import '../../app/format.dart';
import '../../app/theme.dart';
import '../../app/versions.dart';
import '../../core/services/backend_client.dart';
import '../../core/services/settings_service.dart';

/// Backend URL / API key / mesh quality / cache cap / about (ARCHITECTURE.md §3.4).
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.services});

  final AppServices services;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late final TextEditingController _url = TextEditingController(
    text: _settings.backendUrl,
  );
  late final TextEditingController _apiKey = TextEditingController(
    text: _settings.apiKey,
  );
  bool _showKey = false;
  bool _testing = false;
  String? _testResult;
  int? _diskUsage;

  AppSettings get _settings => widget.services.settings.value;

  @override
  void initState() {
    super.initState();
    _refreshUsage();
  }

  @override
  void dispose() {
    _url.dispose();
    _apiKey.dispose();
    super.dispose();
  }

  Future<void> _refreshUsage() async {
    final usage = await widget.services.cache.diskUsage();
    if (mounted) setState(() => _diskUsage = usage);
  }

  // Always derive from the live value: several fields can be edited before
  // the page rebuilds, so a build-time snapshot would clobber earlier edits.
  Future<void> _save(AppSettings Function(AppSettings current) change) async {
    await widget.services.settings.update(change(_settings));
    if (mounted) setState(() {});
  }

  Future<void> _testConnection() async {
    final url = _url.text.trim();
    if (url.isEmpty) {
      setState(() => _testResult = 'Enter a server URL first');
      return;
    }
    setState(() {
      _testing = true;
      _testResult = null;
    });
    try {
      final health = await widget.services.backend.health(
        url,
        apiKey: _apiKey.text.trim(),
      );
      final compute = !health.computeConfigured
          ? 'Compute not configured'
          : health.computeReachable == true
          ? 'Compute reachable'
          : 'Compute unreachable';
      _testResult = health.ok
          ? 'OK · v${health.version} · $compute'
          : 'Server reports not ok';
    } on BackendException catch (e) {
      _testResult = 'Failed: $e';
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  Future<void> _setCacheCap(int mb) async {
    await _save((s) => s.copyWith(cacheCapMb: mb));
    final cache = widget.services.cache..sizeCapBytes = _settings.cacheCapBytes;
    await cache.enforceLimits();
    await _refreshUsage();
    if (mounted) setState(() {});
  }

  Future<void> _clearCache() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear cache?'),
        content: const Text(
          'All cached models and the recents list are deleted.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: AppColors.danger),
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await widget.services.cache.clear();
    await _refreshUsage();
  }

  @override
  Widget build(BuildContext context) {
    final settings = _settings;
    final usage = _diskUsage;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(kGap * 2),
        children: [
          const _Section('Meshing server'),
          TextField(
            controller: _url,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: 'Backend URL',
              hintText: 'http://192.168.1.10:8080',
            ),
            onChanged: (v) => _save((s) => s.copyWith(backendUrl: v.trim())),
          ),
          const SizedBox(height: kGap * 1.5),
          TextField(
            controller: _apiKey,
            obscureText: !_showKey,
            autocorrect: false,
            enableSuggestions: false,
            decoration: InputDecoration(
              labelText: 'API key',
              suffixIcon: IconButton(
                icon: Icon(
                  _showKey
                      ? Icons.visibility_off_outlined
                      : Icons.visibility_outlined,
                ),
                tooltip: _showKey ? 'Hide' : 'Show',
                onPressed: () => setState(() => _showKey = !_showKey),
              ),
            ),
            onChanged: (v) => _save((s) => s.copyWith(apiKey: v.trim())),
          ),
          const SizedBox(height: kGap * 1.5),
          const _Label('Mesh quality'),
          SegmentedButton<MeshQuality>(
            segments: const [
              ButtonSegment(value: MeshQuality.draft, label: Text('Draft')),
              ButtonSegment(
                value: MeshQuality.standard,
                label: Text('Default'),
              ),
              ButtonSegment(value: MeshQuality.fine, label: Text('Fine')),
            ],
            selected: {settings.meshQuality},
            showSelectedIcon: false,
            onSelectionChanged: (sel) =>
                _save((s) => s.copyWith(meshQuality: sel.first)),
          ),
          const SizedBox(height: kGap * 1.5),
          Row(
            children: [
              OutlinedButton(
                onPressed: _testing ? null : _testConnection,
                child: Text(_testing ? 'Testing…' : 'Test connection'),
              ),
              const SizedBox(width: kGap * 1.5),
              Expanded(
                child: Text(
                  _testResult ?? '',
                  style: TextStyle(
                    color: (_testResult ?? '').startsWith('OK')
                        ? AppColors.text
                        : AppColors.danger,
                    fontSize: 12,
                  ),
                ),
              ),
            ],
          ),
          const _Section('Cache'),
          const _Label('Size cap'),
          SegmentedButton<int>(
            segments: [
              for (final mb in AppSettings.cacheCapChoicesMb)
                ButtonSegment(
                  value: mb,
                  label: Text(mb >= 1024 ? '${mb ~/ 1024} GB' : '$mb MB'),
                ),
            ],
            selected: {settings.cacheCapMb},
            showSelectedIcon: false,
            onSelectionChanged: (s) => _setCacheCap(s.first),
          ),
          const SizedBox(height: kGap * 1.5),
          Row(
            children: [
              OutlinedButton(
                onPressed: _clearCache,
                child: const Text('Clear cache'),
              ),
              const SizedBox(width: kGap * 1.5),
              Text(
                usage == null ? '' : '${formatBytes(usage)} used',
                style: monoNumbers.copyWith(
                  color: AppColors.muted,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          const _Section('About'),
          const Text(
            'Files are parsed on the phone with rhino3dm and rendered with three.js. '
            'The server is only needed for files saved without render meshes.',
            style: TextStyle(color: AppColors.muted, fontSize: 12),
          ),
          const SizedBox(height: kGap),
          const _KeyValue('three.js', VendoredVersions.three),
          const _KeyValue('rhino3dm', VendoredVersions.rhino3dm),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.title);

  final String title;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: kGap * 3, bottom: kGap),
    child: Text(
      title.toUpperCase(),
      style: const TextStyle(
        color: AppColors.muted,
        fontSize: 11,
        letterSpacing: 1,
      ),
    ),
  );
}

class _Label extends StatelessWidget {
  const _Label(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: kGap / 2),
    child: Text(
      text,
      style: const TextStyle(color: AppColors.muted, fontSize: 12),
    ),
  );
}

class _KeyValue extends StatelessWidget {
  const _KeyValue(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: AppColors.text, fontSize: 13),
          ),
        ),
        Text(
          value,
          style: monoNumbers.copyWith(color: AppColors.text, fontSize: 13),
        ),
      ],
    ),
  );
}
