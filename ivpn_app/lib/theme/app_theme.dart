import 'package:flutter/material.dart';

class AppTheme {
  static const Color primaryColor = Color(0xFF00E5FF); // Neon Cyan/Blue
  static const Color accentColor = Color(0xFF2979FF); // Electric Blue
  static const Color backgroundColor = Color(0xFF0F172A); // Deep Navy/Black
  static const Color surfaceColor = Color(0xFF1E293B); // Slightly lighter navy
  static const Color errorColor = Color(0xFFFF5252);

  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: backgroundColor,
      primaryColor: primaryColor,
      colorScheme: const ColorScheme.dark(
        primary: primaryColor,
        secondary: accentColor,
        surface: surfaceColor,
        background: backgroundColor,
        error: errorColor,
      ),
      fontFamily: 'Roboto', // Default, or custom if added
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: primaryColor,
          foregroundColor: Colors.black,
          elevation: 8,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(30),
          ),
          shadowColor: primaryColor.withOpacity(0.5),
        ),
      ),
      textTheme: const TextTheme(
        displayLarge: TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: Colors.white),
        displayMedium: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.white70),
        bodyLarge: TextStyle(fontSize: 16, color: Colors.white60),
      ),
    );
  }
}
