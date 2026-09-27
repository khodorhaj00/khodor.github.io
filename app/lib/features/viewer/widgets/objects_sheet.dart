import 'package:flutter/material.dart';

import '../../../app/format.dart';
import '../../../app/stitch.dart';
import '../../../app/theme.dart';
import '../../../core/models/viewer_options.dart';

/// Per object type: whether it is drawn (Show) and whether a tap can select
/// it (Select, Rhino's selection filter). Lists the types the file contains;
/// keeps its own copy of the switches so they respond instantly while the
/// page mirrors them through the callbacks.
class ObjectsSheet extends StatefulWidget {
  const ObjectsSheet({
    super.key,
    required this.counts,
    required this.visible,
    required this.pickable,
    required this.onVisibleChanged,
    required this.onPickableChanged,
  });

  final Map<ObjectCategory, int> counts;
  final Map<ObjectCategory, bool> visible;
  final Map<ObjectCategory, bool> pickable;
  final void Function(ObjectCategory category, bool visible) onVisibleChanged;
  final void Function(ObjectCategory category, bool pickable) onPickableChanged;

  // Transparent barrier: the effect on the model stays visible.
  static Future<void> show(
    BuildContext context, {
    required Map<ObjectCategory, int> counts,
    required Map<ObjectCategory, bool> visible,
    required Map<ObjectCategory, bool> pickable,
    required void Function(ObjectCategory, bool) onVisibleChanged,
    required void Function(ObjectCategory, bool) onPickableChanged,
  }) => showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    barrierColor: Colors.transparent,
    builder: (_) => ObjectsSheet(
      counts: counts,
      visible: visible,
      pickable: pickable,
      onVisibleChanged: onVisibleChanged,
      onPickableChanged: onPickableChanged,
    ),
  );

  @override
  State<ObjectsSheet> createState() => _ObjectsSheetState();
}

class _ObjectsSheetState extends State<ObjectsSheet> {
  late final Map<ObjectCategory, bool> _visible = Map.of(widget.visible);
  late final Map<ObjectCategory, bool> _pickable = Map.of(widget.pickable);

  /// The categories present in the file; all of them when the page did not
  /// report counts.
  List<ObjectCategory> get _listed {
    if (widget.counts.isEmpty) return ObjectCategory.values;
    return [
      for (final category in ObjectCategory.values)
        if ((widget.counts[category] ?? 0) > 0) category,
    ];
  }

  void _setVisible(ObjectCategory category, bool value) {
    setState(() => _visible[category] = value);
    widget.onVisibleChanged(category, value);
  }

  void _setPickable(ObjectCategory category, bool value) {
    setState(() => _pickable[category] = value);
    widget.onPickableChanged(category, value);
  }

  @override
  Widget build(BuildContext context) {
    final listed = _listed;
    return SafeArea(
      top: false,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(kGap * 2, kGap * 2, kGap, kGap),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TechLabel('CAD inspect', size: 10),
                      Text(
                        'OBJECTS',
                        style: TextStyle(
                          fontFamily: kTitleFamily,
                          color: AppColors.text,
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
                _ColumnLabel('Show'),
                _ColumnLabel('Select'),
              ],
            ),
          ),
          const Divider(),
          if (listed.isEmpty)
            const Padding(
              padding: EdgeInsets.all(kGap * 3),
              child: Text(
                'Nothing to show',
                style: TextStyle(color: AppColors.muted),
              ),
            )
          else
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final category in listed)
                    _CategoryRow(
                      category: category,
                      count: widget.counts[category],
                      visible: _visible[category] ?? true,
                      pickable: _pickable[category] ?? true,
                      onVisible: (v) => _setVisible(category, v),
                      onPickable: (v) => _setPickable(category, v),
                    ),
                ],
              ),
            ),
          const Padding(
            padding: EdgeInsets.fromLTRB(kGap * 2, kGap, kGap * 2, kGap * 2),
            child: Text(
              'Select sets what a tap can pick. Objects inside a block follow '
              'Blocks.',
              style: TextStyle(color: AppColors.muted, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

class _ColumnLabel extends StatelessWidget {
  const _ColumnLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 56,
    child: Text(
      text,
      textAlign: TextAlign.center,
      style: const TextStyle(color: AppColors.muted, fontSize: 11),
    ),
  );
}

class _CategoryRow extends StatelessWidget {
  const _CategoryRow({
    required this.category,
    required this.count,
    required this.visible,
    required this.pickable,
    required this.onVisible,
    required this.onPickable,
  });

  final ObjectCategory category;
  final int? count;
  final bool visible;
  final bool pickable;
  final ValueChanged<bool> onVisible;
  final ValueChanged<bool> onPickable;

  static IconData _icon(ObjectCategory category) => switch (category) {
    ObjectCategory.surfaces => Icons.view_in_ar_outlined,
    ObjectCategory.meshes => Icons.change_history,
    ObjectCategory.curves => Icons.gesture,
    ObjectCategory.points => Icons.scatter_plot_outlined,
    ObjectCategory.annotations => Icons.straighten,
    ObjectCategory.hatches => Icons.texture,
    ObjectCategory.blocks => Icons.widgets_outlined,
  };

  @override
  Widget build(BuildContext context) {
    final count = this.count;
    return Padding(
      padding: const EdgeInsets.only(left: kGap * 2, right: kGap),
      child: Row(
        children: [
          Icon(_icon(category), size: 18, color: AppColors.muted),
          const SizedBox(width: kGap * 1.5),
          Expanded(
            child: Text(
              category.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.text, fontSize: 14),
            ),
          ),
          if (count != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: kGap),
              child: Text(
                formatCount(count),
                style: monoNumbers.copyWith(
                  color: AppColors.muted,
                  fontSize: 12,
                ),
              ),
            ),
          SizedBox(
            width: 56,
            child: Checkbox(
              value: visible,
              semanticLabel: 'Show ${category.label}',
              onChanged: (v) => onVisible(v ?? false),
            ),
          ),
          SizedBox(
            width: 56,
            child: Checkbox(
              value: pickable,
              semanticLabel: 'Select ${category.label}',
              onChanged: (v) => onPickable(v ?? false),
            ),
          ),
        ],
      ),
    );
  }
}
