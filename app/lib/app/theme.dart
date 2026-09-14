import 'package:flutter/material.dart';

/// Visual tokens (ARCHITECTURE.md §3.4): dark, industrial, no decoration.
abstract final class AppColors {
  static const Color bg = Color(0xFF0E1013);
  static const Color surface = Color(0xFF161A1F);
  static const Color border = Color(0xFF262B33);
  static const Color text = Color(0xFFE6E8EB);
  static const Color muted = Color(0xFF8B93A1);
  static const Color accent = Color(0xFFFFB020);
  static const Color danger = Color(0xFFFF4D4F);

  /// Foreground on accent-filled surfaces.
  static const Color onAccent = Color(0xFF14110A);
}

/// 8 px grid.
const double kGap = 8;

const BorderSide kBorder = BorderSide(color: AppColors.border);

const BorderRadius kRadius = BorderRadius.all(Radius.circular(4));

/// Numbers are always monospace with tabular figures.
const TextStyle monoNumbers = TextStyle(
  fontFamily: 'monospace',
  fontFeatures: [FontFeature.tabularFigures()],
);

ThemeData buildAppTheme() {
  final scheme =
      ColorScheme.fromSeed(
        seedColor: AppColors.accent,
        brightness: Brightness.dark,
      ).copyWith(
        primary: AppColors.accent,
        onPrimary: AppColors.onAccent,
        surface: AppColors.surface,
        onSurface: AppColors.text,
        onSurfaceVariant: AppColors.muted,
        outline: AppColors.border,
        outlineVariant: AppColors.border,
        error: AppColors.danger,
        onError: AppColors.text,
        surfaceContainerHighest: AppColors.surface,
        surfaceContainerHigh: AppColors.surface,
        surfaceContainer: AppColors.surface,
        surfaceContainerLow: AppColors.bg,
        surfaceContainerLowest: AppColors.bg,
      );
  const shape = RoundedRectangleBorder(side: kBorder, borderRadius: kRadius);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.bg,
    canvasColor: AppColors.bg,
    dividerColor: AppColors.border,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      foregroundColor: AppColors.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      shape: Border(bottom: kBorder),
      titleTextStyle: TextStyle(
        color: AppColors.text,
        fontSize: 18,
        fontWeight: FontWeight.w600,
      ),
    ),
    cardTheme: const CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: shape,
    ),
    dialogTheme: const DialogThemeData(
      backgroundColor: AppColors.surface,
      elevation: 0,
      shape: shape,
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: AppColors.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        side: kBorder,
        borderRadius: BorderRadius.vertical(top: Radius.circular(8)),
      ),
    ),
    popupMenuTheme: const PopupMenuThemeData(
      color: AppColors.surface,
      elevation: 0,
      shape: shape,
      textStyle: TextStyle(color: AppColors.text, fontSize: 14),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: AppColors.surface,
      contentTextStyle: TextStyle(color: AppColors.text),
      actionTextColor: AppColors.accent,
      elevation: 0,
      shape: shape,
      behavior: SnackBarBehavior.floating,
    ),
    dividerTheme: const DividerThemeData(
      color: AppColors.border,
      thickness: 1,
      space: 1,
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: AppColors.bg,
      border: OutlineInputBorder(borderSide: kBorder, borderRadius: kRadius),
      enabledBorder: OutlineInputBorder(
        borderSide: kBorder,
        borderRadius: kRadius,
      ),
      focusedBorder: OutlineInputBorder(
        borderSide: BorderSide(color: AppColors.accent),
        borderRadius: kRadius,
      ),
      labelStyle: TextStyle(color: AppColors.muted),
      hintStyle: TextStyle(color: AppColors.muted),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: AppColors.onAccent,
        elevation: 0,
        shape: const RoundedRectangleBorder(borderRadius: kRadius),
        minimumSize: const Size(0, 48),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.text,
        side: kBorder,
        shape: const RoundedRectangleBorder(borderRadius: kRadius),
        minimumSize: const Size(0, 40),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: AppColors.accent,
        shape: const RoundedRectangleBorder(borderRadius: kRadius),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        foregroundColor: AppColors.text,
        selectedForegroundColor: AppColors.onAccent,
        selectedBackgroundColor: AppColors.accent,
        side: kBorder,
        shape: const RoundedRectangleBorder(borderRadius: kRadius),
      ),
    ),
    listTileTheme: const ListTileThemeData(
      textColor: AppColors.text,
      iconColor: AppColors.muted,
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: AppColors.accent,
      linearTrackColor: AppColors.border,
      circularTrackColor: AppColors.border,
    ),
    iconTheme: const IconThemeData(color: AppColors.text),
  );
}
