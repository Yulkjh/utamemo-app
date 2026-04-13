import os, sys, django

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'myproject'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from users.models import TrainingDataReview

# All reviews
all_reviews = TrainingDataReview.objects.all()
print(f"Total TrainingDataReview records: {all_reviews.count()}")

# Untrained (reviewed but not yet trained)
untrained = TrainingDataReview.objects.filter(trained_at__isnull=True)
untrained_indices = sorted(set(untrained.values_list('data_index', flat=True)))
print(f"Reviewed & untrained: {len(untrained_indices)} records")
print(f"Indices: {untrained_indices}")

# Already trained
trained = TrainingDataReview.objects.filter(trained_at__isnull=False)
trained_indices = sorted(set(trained.values_list('data_index', flat=True)))
print(f"Already trained: {len(trained_indices)} records")
print(f"Indices: {trained_indices}")
