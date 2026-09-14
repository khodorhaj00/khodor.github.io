import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/theme.dart';
import '../../../core/models/model_stats.dart';

/// Bottom sheet listing layers with checkbox, colour swatch and object count.
/// Keeps its own copy of the visibility flags so toggles render instantly;
/// the page mirrors the changes through the callbacks.
class LayersSheet extends StatefulWidget {
  const LayersSheet({
    super.key,
    required this.layers,
    required this.onLayerToggled,
    required this.onAllToggled,
  });

  final List<LayerInfo> layers;
  final void Function(int index, bool visible) onLayerToggled;
  final ValueChanged<bool> onAllToggled;

  static Future<void> show(
    BuildContext context, {
    required List<LayerInfo> layers,
    required void Function(int index, bool visible) onLayerToggled,
    required ValueChanged<bool> onAllToggled,
  }) => showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
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
  late List<LayerInfo> _layers = List.of(widget.layers);

  void _toggle(int position, bool visible) {
    setState(
      () => _layers[position] = _layers[position].copyWith(visible: visible),
    );
    widget.onLayerToggled(_layers[position].index, visible);
  }

  void _all(bool visible) {
    setState(() {
      _layers = [for (final l in _layers) l.copyWith(visible: visible)];
    });
    widget.onAllToggled(visible);
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kGap * 2, kGap, kGap, 0),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'Layers',
                  style: TextStyle(
                    color: AppColors.text,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              TextButton(onPressed: () => _all(true), child: const Text('All')),
              TextButton(
                onPressed: () => _all(false),
                child: const Text('None'),
              ),
            ],
          ),
        ),
        const Divider(),
        Flexible(
          child: _layers.isEmpty
              ? const Padding(
                  padding: EdgeInsets.all(kGap * 3),
                  child: Text(
                    'No layers',
                    style: TextStyle(color: AppColors.muted),
                  ),
                )
              : ListView.builder(
                  shrinkWrap: true,
                  itemCount: _layers.length,
                  itemBuilder: (_, i) => _LayerRow(
                    layer: _layers[i],
                    onChanged: (v) => _toggle(i, v),
                  ),
                ),
        ),
      ],
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
                    style: const TextStyle(color: AppColors.text, fontSize: 14),
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
