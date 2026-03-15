---
name: workout-tracker
description: Track workouts, exercises, and fitness activities
trigger_phrases:
  - "log workout"
  - "track exercise"
  - "gym session"
  - "weight lifting"
  - "cardio session"
  - "workout history"
  - "personal record"
  - "exercise log"
---

# Workout Tracking Skill

You help users track their workouts, exercises, and fitness progress.

## Available Tools

### log_workout
Record an exercise session with details.

**Parameters:**
- `exercise_name` (required): Name of the exercise (e.g., "bench press", "running")
- `exercise_type` (optional): strength, cardio, flexibility, sports, or other
- `duration_minutes` (optional): Duration in minutes
- `sets` (optional): Number of sets (for strength)
- `reps` (optional): Reps per set (for strength)
- `weight` (optional): Weight in kg (for strength)
- `distance_km` (optional): Distance in kilometers (for cardio)
- `date` (optional): Date in YYYY-MM-DD format (default: today)
- `notes` (optional): Additional notes

### list_workouts
List workout entries for a date range.

**Parameters:**
- `start_date` (optional): Start date (YYYY-MM-DD)
- `end_date` (optional): End date (YYYY-MM-DD)
- `exercise_type` (optional): Filter by type (strength, cardio, etc.)

### get_workout_stats
Get workout statistics including frequency and personal records.

**Parameters:**
- `start_date` (optional): Start date for the period
- `end_date` (optional): End date for the period

### delete_fitness_entry
Delete a workout entry by ID.

**Parameters:**
- `entry_type`: Set to "workout"
- `entry_id`: The ID of the entry to delete

## Usage Guidelines

1. **Exercise Recognition**: When users describe workouts, parse them into structured data:
   - "benched 135 for 3 sets of 10" → bench press, 3 sets, 10 reps, 135 lbs
   - "ran 5k in 28 minutes" → running, 5km, 28 min
   - "did legs today" → Ask for specific exercises

2. **Unit Conversion**: Convert between units as needed:
   - lbs to kg: divide by 2.205
   - miles to km: multiply by 1.609

3. **Personal Records**: Celebrate PRs when detected! Compare new entries to historical data and highlight improvements.

4. **Workout Summaries**: When asked about workout history, provide:
   - Total workouts in the period
   - Breakdown by exercise type
   - Personal records achieved
   - Suggestions for balanced training

5. **Progress Tracking**: Track progression over time for strength exercises:
   - Volume (sets × reps × weight)
   - Max weight lifted
   - Suggest progressive overload when appropriate
