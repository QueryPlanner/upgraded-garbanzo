"""Fitness tracking module for calories and workouts."""

from .models import CalorieEntry, ExerciseType, MealType, WorkoutEntry
from .storage import FitnessStorage, get_fitness_storage
from .tools import (
    add_calories,
    delete_fitness_entry,
    get_calorie_stats,
    get_workout_stats,
    list_calories,
    list_workouts,
    log_workout,
)

__all__ = [
    "CalorieEntry",
    "ExerciseType",
    "FitnessStorage",
    "MealType",
    "WorkoutEntry",
    "add_calories",
    "delete_fitness_entry",
    "get_calorie_stats",
    "get_fitness_storage",
    "get_workout_stats",
    "list_calories",
    "list_workouts",
    "log_workout",
]
