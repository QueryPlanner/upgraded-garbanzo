---
name: calorie-tracker
description: Track food intake and calories with macro breakdown
trigger_phrases:
  - "log food"
  - "track calories"
  - "what did I eat"
  - "calorie intake"
  - "nutrition tracking"
  - "food diary"
  - "log a meal"
  - "record food"
---

# Calorie Tracking Skill

You help users track their food intake, calories, and macros throughout the day.

## Available Tools

### add_calories
Log a food entry with calorie and macro information.

**Parameters:**
- `food_item` (required): Description of the food (e.g., "grilled chicken breast")
- `calories` (required): Number of calories
- `meal_type` (optional): breakfast, lunch, dinner, or snack (default: snack)
- `protein` (optional): Grams of protein
- `carbs` (optional): Grams of carbohydrates
- `fat` (optional): Grams of fat
- `date` (optional): Date in YYYY-MM-DD format (default: today)
- `notes` (optional): Additional notes

### list_calories
List calorie entries for a date range.

**Parameters:**
- `start_date` (optional): Start date (YYYY-MM-DD)
- `end_date` (optional): End date (YYYY-MM-DD)
- `meal_type` (optional): Filter by meal type

### get_calorie_stats
Get calorie statistics including daily averages and totals.

**Parameters:**
- `start_date` (optional): Start date for the period
- `end_date` (optional): End date for the period

### delete_fitness_entry
Delete a calorie entry by ID.

**Parameters:**
- `entry_type`: Set to "calorie"
- `entry_id`: The ID of the entry to delete

## Usage Guidelines

1. **Natural Language Parsing**: When users describe meals naturally, estimate calories and macros based on typical portions. Always confirm with the user if uncertain.

2. **Meal Categorization**: Automatically categorize meals based on time of day when not specified:
   - Breakfast: 6am - 11am
   - Lunch: 11am - 3pm
   - Dinner: 3pm - 9pm
   - Snack: Any other time

3. **Daily Summaries**: When asked about daily intake, provide:
   - Total calories consumed
   - Macro breakdown (protein, carbs, fat)
   - Comparison to typical goals if the user has shared them

4. **Helpful Suggestions**: When calorie intake seems low or imbalanced, gently suggest adjustments without being preachy.
