import 'package:flutter/material.dart';

import 'theme.dart';

// ---------------------------------------------------------------------------------------
// The Stitch look: dark panels with 1 px borders, amber accents, upper-case monospace
// technical labels. Every screen builds from these, so a change here restyles the app
// (docs/CUSTOMISING.md).
// ---------------------------------------------------------------------------------------

/// Upper-cases [text] and draws it as a technical label.
class TechLabel extends StatelessWidget {
  const TechLabel(
    this.text, {
    super.key,
    this.color,
    this.size,
    this.maxLines = 1,
  });

  final String text;
  final Color? color;
  final double? size;
  final int maxLines;

  @override
  Widget build(BuildContext context) => Text(
    text.toUpperCase(),
    maxLines: maxLines,
    overflow: TextOverflow.ellipsis,
    style: techLabel.copyWith(color: color, fontSize: size),
  );
}

/// The app's logo tile: the bust in a bordered square.
class LogoTile extends StatelessWidget {
  const LogoTile({super.key, this.size = 36});

  final double size;

  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: const BoxDecoration(
      color: AppColors.inset,
      border: Border.fromBorderSide(kBorder),
      borderRadius: kRadius,
    ),
    padding: const EdgeInsets.all(2),
    child: Image.asset('assets/branding/logo.png', fit: BoxFit.contain),
  );
}

/// The round amber button at the top right of every screen: Settings.
class SettingsButton extends StatelessWidget {
  const SettingsButton({super.key, required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: 'Settings',
    child: Material(
      color: AppColors.accent,
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onPressed,
        child: const SizedBox.square(
          dimension: 40,
          child: Icon(
            Icons.settings_outlined,
            color: AppColors.onAccent,
            size: 22,
          ),
        ),
      ),
    ),
  );
}

/// A screen header: optional back button, the logo, a small kicker above a title,
/// then [actions] and, when given, the Settings button.
class StitchHeader extends StatelessWidget {
  const StitchHeader({
    super.key,
    required this.kicker,
    required this.title,
    this.onBack,
    this.onSettings,
    this.actions = const [],
    this.translucent = false,
  });

  final String kicker;
  final String title;
  final VoidCallback? onBack;
  final VoidCallback? onSettings;
  final List<Widget> actions;

  /// Over the 3D view the header lets the model show through a little.
  final bool translucent;

  static const double height = 64;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: height,
      decoration: BoxDecoration(
        color: translucent
            ? AppColors.bg.withValues(alpha: 0.88)
            : AppColors.bg,
        border: const Border(bottom: kBorder),
      ),
      padding: EdgeInsets.only(
        left: onBack == null ? kGap * 2 : 0,
        right: kGap * 1.5,
      ),
      child: Row(
        children: [
          if (onBack != null)
            IconButton(
              onPressed: onBack,
              icon: const Icon(Icons.arrow_back),
              tooltip: 'Back',
            ),
          const LogoTile(),
          const SizedBox(width: kGap * 1.5),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TechLabel(kicker, size: 10),
                const SizedBox(height: 2),
                Text(
                  title.toUpperCase(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontFamily: kTitleFamily,
                    color: AppColors.text,
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
          ),
          ...actions,
          if (onSettings != null) ...[
            const SizedBox(width: kGap),
            SettingsButton(onPressed: onSettings!),
          ],
        ],
      ),
    );
  }
}

/// A dark panel with a 1 px border; [accent] draws the amber bar on its left edge.
class StitchPanel extends StatelessWidget {
  const StitchPanel({
    super.key,
    required this.child,
    this.accent = false,
    this.padding = const EdgeInsets.all(kGap * 1.5),
    this.color = AppColors.surface,
  });

  final Widget child;
  final bool accent;
  final EdgeInsetsGeometry padding;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final body = Padding(padding: padding, child: child);
    return Container(
      // Flutter cannot round a border of mixed colours, so the amber bar is a
      // strip painted inside the clipped, uniformly bordered box.
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: color,
        border: const Border.fromBorderSide(kBorder),
        borderRadius: kRadius,
      ),
      child: accent
          ? IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const ColoredBox(
                    color: AppColors.accent,
                    child: SizedBox(width: 3),
                  ),
                  Expanded(child: body),
                ],
              ),
            )
          : body,
    );
  }
}

/// A small outlined tag: `MESHED`, `NURBS`, `542K TRIS`.
class StitchChip extends StatelessWidget {
  const StitchChip(
    this.text, {
    super.key,
    this.color = AppColors.accent,
    this.filled = false,
  });

  final String text;
  final Color color;
  final bool filled;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
    decoration: BoxDecoration(
      color: filled ? color.withValues(alpha: 0.15) : null,
      border: Border.all(color: color),
      borderRadius: kRadius,
    ),
    child: Text(
      text.toUpperCase(),
      style: techLabel.copyWith(color: color, fontSize: 10, letterSpacing: 1),
    ),
  );
}

/// A label over a value, for the telemetry boxes and the part card.
class StatBox extends StatelessWidget {
  const StatBox({
    super.key,
    required this.label,
    required this.value,
    this.valueColor,
  });

  final String label;
  final String value;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(kGap),
    decoration: const BoxDecoration(
      color: AppColors.inset,
      border: Border.fromBorderSide(kBorder),
      borderRadius: kRadius,
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        TechLabel(label, size: 10),
        const SizedBox(height: 4),
        Text(
          value,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: monoNumbers.copyWith(
            color: valueColor ?? AppColors.text,
            fontSize: 14,
          ),
        ),
      ],
    ),
  );
}

/// A section heading inside a screen: icon, label, optional trailing text.
class SectionHeading extends StatelessWidget {
  const SectionHeading({
    super.key,
    required this.icon,
    required this.label,
    this.trailing,
  });

  final IconData icon;
  final String label;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: kGap * 2, bottom: kGap),
    child: Row(
      children: [
        Icon(icon, size: 16, color: AppColors.text),
        const SizedBox(width: kGap),
        Expanded(child: TechLabel(label, color: AppColors.text, size: 12)),
        ?trailing,
      ],
    ),
  );
}
