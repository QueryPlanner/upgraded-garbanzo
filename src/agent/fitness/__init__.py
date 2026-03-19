"""Fitness tracking module for calories and workouts."""

from .models import CalorieEntry, ExerciseType, MealType, WorkoutEntry
from .storage import FitnessStorage, get_fitness_storage

__all__ = [
    "CalorieEntry",
    "ExerciseType",
    "MealType",
    "WorkoutEntry",
    "FitnessStorage",
    "get_fitness_storage",
]
