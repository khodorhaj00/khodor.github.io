import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/bridge/viewer_bridge.dart';

const double kViewerToolbarHeight = 64;

/// Fit · Views · Display mode · Layers · Grid · Ortho (ARCHITECTURE.md §3.4).
class ViewerToolbar extends StatelessWidget {
  const ViewerToolbar({
    super.key,
    required this.displayMode,
    required this.projection,
    required this.grid,
    required this.onFit,
    required this.onView,
    required this.onDisplayMode,
    required this.onLayers,
    required this.onGrid,
    required this.onProjection,
  });

  final DisplayMode displayMode;
  final Projection projection;
  final bool grid;
  final VoidCallback onFit;
  final ValueChanged<ViewerView> onView;
  final ValueChanged<DisplayMode> onDisplayMode;
  final VoidCallback onLayers;
  final ValueChanged<bool> onGrid;
  final ValueChanged<Projection> onProjection;

  @override
  Widget build(BuildContext context) {
    final ortho = projection == Projection.ortho;
    return Container(
      height: kViewerToolbarHeight,
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border(top: kBorder),
      ),
      child: Row(
        children: [
          Expanded(
            child: _ToolButton(
              icon: Icons.fit_screen_outlined,
              label: 'Fit',
              onTap: onFit,
            ),
          ),
          Expanded(
            child: PopupMenuButton<ViewerView>(
              tooltip: 'Views',
              onSelected: onView,
              itemBuilder: (_) => [
                for (final view in ViewerView.values)
                  PopupMenuItem(value: view, child: Text(_viewLabel(view))),
              ],
              child: const _ToolButton(
                icon: Icons.view_in_ar_outlined,
                label: 'Views',
              ),
            ),
          ),
          Expanded(
            child: PopupMenuButton<DisplayMode>(
              tooltip: 'Display mode',
              initialValue: displayMode,
              onSelected: onDisplayMode,
              itemBuilder: (_) => [
                for (final mode in DisplayMode.values)
                  PopupMenuItem(value: mode, child: Text(mode.label)),
              ],
              child: const _ToolButton(
                icon: Icons.layers_outlined,
                label: 'Display',
              ),
            ),
          ),
          Expanded(
            child: _ToolButton(
              icon: Icons.checklist_rtl,
              label: 'Layers',
              onTap: onLayers,
            ),
          ),
          Expanded(
            child: _ToolButton(
              icon: Icons.grid_4x4,
              label: 'Grid',
              active: grid,
              onTap: () => onGrid(!grid),
            ),
          ),
          Expanded(
            child: _ToolButton(
              icon: Icons.crop_square_outlined,
              label: 'Ortho',
              active: ortho,
              onTap: () => onProjection(
                ortho ? Projection.perspective : Projection.ortho,
              ),
            ),
          ),
        ],
      ),
    );
  }

  static String _viewLabel(ViewerView view) => switch (view) {
    ViewerView.iso => 'Perspective',
    ViewerView.top => 'Top',
    ViewerView.bottom => 'Bottom',
    ViewerView.front => 'Front',
    ViewerView.back => 'Back',
    ViewerView.left => 'Left',
    ViewerView.right => 'Right',
  };
}

class _ToolButton extends StatelessWidget {
  const _ToolButton({
    required this.icon,
    required this.label,
    this.active = false,
    this.onTap,
  });

  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final color = active ? AppColors.accent : AppColors.text;
    final body = SizedBox(
      height: kViewerToolbarHeight,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: color, size: 22),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(color: color, fontSize: 10)),
        ],
      ),
    );
    return onTap == null ? body : InkWell(onTap: onTap, child: body);
  }
}
