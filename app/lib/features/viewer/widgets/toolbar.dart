import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../core/bridge/viewer_bridge.dart';

const double kViewerToolbarHeight = 64;

/// Margin for the page's floating SnackBars so they land above the toolbar
/// (the Scaffold already keeps them above the system bottom inset).
const EdgeInsets kViewerSnackBarMargin = EdgeInsets.fromLTRB(
  kGap,
  0,
  kGap,
  kViewerToolbarHeight + kGap,
);

enum _ViewToggle { ortho, grid }

enum _DisplayToggle { fullRender }

/// Fit · Views · Display · Layers · Objects · Caliper (ARCHITECTURE.md §3.4).
/// The Views menu also holds the Orthographic and Grid switches, the Display
/// menu the full-render switch.
class ViewerToolbar extends StatelessWidget {
  const ViewerToolbar({
    super.key,
    required this.displayMode,
    this.renderQuality = RenderQuality.basic,
    required this.projection,
    required this.grid,
    this.measuring = false,
    required this.onFit,
    required this.onView,
    required this.onDisplayMode,
    this.onRenderQuality,
    required this.onLayers,
    this.onObjects,
    this.onMeasure,
    required this.onGrid,
    required this.onProjection,
  });

  final DisplayMode displayMode;
  final RenderQuality renderQuality;
  final Projection projection;
  final bool grid;
  final bool measuring;
  final VoidCallback onFit;
  final ValueChanged<ViewerView> onView;
  final ValueChanged<DisplayMode> onDisplayMode;
  final ValueChanged<RenderQuality>? onRenderQuality;
  final VoidCallback onLayers;
  final VoidCallback? onObjects;
  final VoidCallback? onMeasure;
  final ValueChanged<bool> onGrid;
  final ValueChanged<Projection> onProjection;

  void _onViewsItem(Object item) {
    switch (item) {
      case ViewerView view:
        onView(view);
      case _ViewToggle.ortho:
        onProjection(
          projection == Projection.ortho
              ? Projection.perspective
              : Projection.ortho,
        );
      case _ViewToggle.grid:
        onGrid(!grid);
    }
  }

  void _onDisplayItem(Object item) {
    switch (item) {
      case DisplayMode mode:
        onDisplayMode(mode);
      case _DisplayToggle.fullRender:
        final full = renderQuality == RenderQuality.full;
        onRenderQuality?.call(full ? RenderQuality.basic : RenderQuality.full);
        // Asking for textures and shadows means asking to see them.
        if (!full && displayMode != DisplayMode.rendered) {
          onDisplayMode(DisplayMode.rendered);
        }
    }
  }

  @override
  Widget build(BuildContext context) {
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
            child: PopupMenuButton<Object>(
              tooltip: 'Views',
              onSelected: _onViewsItem,
              itemBuilder: (_) => [
                for (final view in ViewerView.values)
                  PopupMenuItem(value: view, child: Text(_viewLabel(view))),
                const PopupMenuDivider(),
                CheckedPopupMenuItem(
                  value: _ViewToggle.ortho,
                  checked: projection == Projection.ortho,
                  child: const Text('Orthographic'),
                ),
                CheckedPopupMenuItem(
                  value: _ViewToggle.grid,
                  checked: grid,
                  child: const Text('Grid'),
                ),
              ],
              child: _ToolButton(
                icon: Icons.view_in_ar_outlined,
                label: 'Views',
                active: projection == Projection.ortho,
              ),
            ),
          ),
          Expanded(
            child: PopupMenuButton<Object>(
              tooltip: 'Display mode',
              initialValue: displayMode,
              onSelected: _onDisplayItem,
              itemBuilder: (_) => [
                for (final mode in DisplayMode.values)
                  PopupMenuItem(value: mode, child: Text(mode.label)),
                if (onRenderQuality != null) ...[
                  const PopupMenuDivider(),
                  CheckedPopupMenuItem(
                    value: _DisplayToggle.fullRender,
                    checked: renderQuality == RenderQuality.full,
                    child: const Text('Textures & shadows'),
                  ),
                ],
              ],
              child: const _ToolButton(icon: Icons.tonality, label: 'Display'),
            ),
          ),
          Expanded(
            child: _ToolButton(
              icon: Icons.layers_outlined,
              label: 'Layers',
              onTap: onLayers,
            ),
          ),
          if (onObjects != null)
            Expanded(
              child: _ToolButton(
                icon: Icons.category_outlined,
                label: 'Objects',
                onTap: onObjects,
              ),
            ),
          if (onMeasure != null)
            Expanded(
              child: _ToolButton(
                icon: Icons.straighten,
                label: 'Caliper',
                active: measuring,
                onTap: onMeasure,
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
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(color: color, fontSize: 11),
          ),
        ],
      ),
    );
    return onTap == null ? body : InkWell(onTap: onTap, child: body);
  }
}
