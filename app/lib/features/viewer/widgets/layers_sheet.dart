import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/stitch.dart';
import '../../../app/theme.dart';
import '../../../core/models/model_stats.dart';

/// Bottom sheet listing layers with checkbox, colour swatch and object count.
/// Keeps its own copy of the visibility flags so toggles render instantly;
/// the page mirrors the changes through the callbacks. Draggable up to most
/// of the screen and filterable, since production files carry 100+ layers.
class LayersSheet extends StatefulWidget {
  const LayersSheet({
    super.key,
    required this.layers,
    required this.onLayerToggled,
    required this.onAllToggled,
  });

  /// Above this many layers the filter field is shown.
  static const int filterThreshold = 12;

  static const double initialSize = 0.5;
  static const double maxSize = 0.9;

  final List<LayerInfo> layers;
  final void Function(int index, bool visible) onLayerToggled;
  final ValueChanged<bool> onAllToggled;

  // The barrier is transparent so a toggle's effect on the model is visible
  // while the sheet is open.
  static Future<void> show(
    BuildContext context, {
    required List<LayerInfo> layers,
    required void Function(int index, bool visible) onLayerToggled,
    required ValueChanged<bool> onAllToggled,
  }) => showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    barrierColor: Colors.transparent,
    builder: (_) => LayersSheet(
      layers: layers,
      onLayerToggled: onLayerToggled,
      onAllToggled: onAllToggled,
    ),
  );

  @override
  State<LayersSheet> createState() => _LayersSheetState();
}

class _LayersSheetState extends State<LayersSheet> {
  late final List<LayerInfo> _layers = List.of(widget.layers);
  final TextEditingController _filter = TextEditingController();

  @override
  void dispose() {
    _filter.dispose();
    super.dispose();
  }

  bool get _filterable => widget.layers.length > LayersSheet.filterThreshold;

  String get _query => _filter.text.trim().toLowerCase();

  /// Positions (into [_layers]) of the layers matching the filter.
  List<int> get _shown {
    final query = _query;
    return [
      for (var i = 0; i < _layers.length; i++)
        if (query.isEmpty ||
            _layers[i].name.toLowerCase().contains(query) ||
            _layers[i].fullPath.toLowerCase().contains(query))
          i,
    ];
  }

  void _toggle(int position, bool visible) {
    setState(
      () => _layers[position] = _layers[position].copyWith(visible: visible),
    );
    widget.onLayerToggled(_layers[position].index, visible);
  }

  /// All/None act on what is listed: every layer when there is no filter,
  /// otherwise only the matches, each reported individually.
  void _all(bool visible) {
    final targets = _shown;
    setState(() {
      for (final position in targets) {
        _layers[position] = _layers[position].copyWith(visible: visible);
      }
    });
    if (_query.isEmpty) {
      widget.onAllToggled(visible);
      return;
    }
    for (final position in targets) {
      widget.onLayerToggled(_layers[position].index, visible);
    }
  }

  /// Flips every listed layer.
  void _invert() {
    final targets = _shown;
    setState(() {
      for (final position in targets) {
        _layers[position] = _layers[position].copyWith(
          visible: !_layers[position].visible,
        );
      }
    });
    for (final position in targets) {
      widget.onLayerToggled(_layers[position].index, _layers[position].visible);
    }
  }

  /// Shows the listed layers and hides every other one. Needs a search, since
  /// without one every layer is listed.
  void _isolate() {
    final targets = _shown.toSet();
    final changed = <int>[];
    setState(() {
      for (var p = 0; p < _layers.length; p++) {
        final visible = targets.contains(p);
        if (_layers[p].visible != visible) {
          _layers[p] = _layers[p].copyWith(visible: visible);
          changed.add(p);
        }
      }
    });
    for (final p in changed) {
      widget.onLayerToggled(_layers[p].index, _layers[p].visible);
    }
  }

  @override
  Widget build(BuildContext context) {
    final shown = _shown;
    final visible = _layers.where((l) => l.visible).length;
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: LayersSheet.initialSize,
      maxChildSize: LayersSheet.maxSize,
      builder: (context, controller) => Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kGap * 2, kGap, kGap * 2, 0),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const TechLabel('CAD inspect', size: 10),
                      Text(
                        _query.isEmpty
                            ? 'LAYERS'
                            : 'LAYERS · ${formatCount(shown.length)} OF ${formatCount(_layers.length)}',
                        style: const TextStyle(
                          fontFamily: kTitleFamily,
                          color: AppColors.text,
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
                TechLabel(
                  '${formatCount(visible)} of ${formatCount(_layers.length)} visible',
                  color: AppColors.accent,
                  size: 10,
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(kGap * 2, kGap, kGap * 2, 0),
            child: Row(
              children: [
                for (final (i, (label, action)) in [
                  ('All vis', shown.isEmpty ? null : () => _all(true)),
                  ('Hide all', shown.isEmpty ? null : () => _all(false)),
                  ('Invert', shown.isEmpty ? null : _invert),
                  (
                    'Isolate',
                    _query.isEmpty || shown.isEmpty ? null : _isolate,
                  ),
                ].indexed) ...[
                  if (i > 0) const SizedBox(width: kGap / 2),
                  Expanded(
                    child: _SheetButton(label: label, onPressed: action),
                  ),
                ],
              ],
            ),
          ),
          if (_filterable)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                kGap * 2,
                kGap / 2,
                kGap * 2,
                kGap,
              ),
              child: TextField(
                controller: _filter,
                onChanged: (_) => setState(() {}),
                autocorrect: false,
                textInputAction: TextInputAction.search,
                style: const TextStyle(color: AppColors.text, fontSize: 14),
                decoration: InputDecoration(
                  isDense: true,
                  hintText: 'SEARCH LAYER NAME...',
                  hintStyle: techLabel,
                  prefixIcon: const Icon(Icons.search, size: 18),
                  suffixIcon: _query.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.close, size: 18),
                          tooltip: 'Clear filter',
                          onPressed: () {
                            _filter.clear();
                            setState(() {});
                          },
                        ),
                ),
              ),
            ),
          const Divider(),
          Expanded(
            child: shown.isEmpty
                ? Padding(
                    padding: const EdgeInsets.all(kGap * 3),
                    child: Text(
                      _layers.isEmpty ? 'No layers' : 'No matching layers',
                      style: const TextStyle(color: AppColors.muted),
                    ),
                  )
                : ListView.builder(
                    controller: controller,
                    itemCount: shown.length,
                    itemBuilder: (_, i) => _LayerRow(
                      layer: _layers[shown[i]],
                      onChanged: (v) => _toggle(shown[i], v),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _LayerRow extends StatelessWidget {
  const _LayerRow({required this.layer, required this.onChanged});

  final LayerInfo layer;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final rgb = layer.rgb;
    final nested = layer.fullPath != layer.name;
    final text = layer.visible ? AppColors.text : AppColors.muted;
    return InkWell(
      onTap: () => onChanged(!layer.visible),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kGap),
        child: Row(
          children: [
            Checkbox(
              value: layer.visible,
              onChanged: (v) => onChanged(v ?? false),
            ),
            Container(
              width: 12,
              height: 12,
              decoration: BoxDecoration(
                color: rgb == null ? AppColors.muted : Color(0xFF000000 | rgb),
                border: Border.all(color: AppColors.border),
              ),
            ),
            const SizedBox(width: kGap * 1.5),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    layer.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: text, fontSize: 14),
                  ),
                  if (nested)
                    Text(
                      layer.fullPath,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.muted,
                        fontSize: 11,
                      ),
                    ),
                ],
              ),
            ),
            Icon(
              layer.visible
                  ? Icons.visibility_outlined
                  : Icons.visibility_off_outlined,
              size: 16,
              color: layer.visible ? AppColors.accent : AppColors.muted,
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: kGap),
              child: Text(
                formatCount(layer.objectCount),
                style: monoNumbers.copyWith(
                  color: AppColors.muted,
                  fontSize: 12,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// ALL VIS / HIDE ALL / INVERT / ISOLATE.
class _SheetButton extends StatelessWidget {
  const _SheetButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => OutlinedButton(
    onPressed: onPressed,
    style: OutlinedButton.styleFrom(
      minimumSize: const Size(0, 36),
      padding: const EdgeInsets.symmetric(horizontal: 4),
    ),
    child: FittedBox(
      child: Text(
        label.toUpperCase(),
        style: techLabel.copyWith(
          color: onPressed == null ? AppColors.border : AppColors.text,
          fontSize: 11,
        ),
      ),
    ),
  );
}
