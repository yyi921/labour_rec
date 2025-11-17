"""
Management command to load reference data from CSV files
"""
from django.core.management.base import BaseCommand
from reconciliation.models import CostCenterSplit
import csv
import os


class Command(BaseCommand):
    help = 'Load reference data (Split_Data.csv) into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--split-data',
            type=str,
            help='Path to Split_Data.csv file',
            default='data/Split_Data.csv'
        )

    def handle(self, *args, **options):
        split_data_path = options['split_data']
        
        self.stdout.write(self.style.SUCCESS('Starting reference data load...'))
        
        # Load Split Data
        if os.path.exists(split_data_path):
            self.load_split_data(split_data_path)
        else:
            self.stdout.write(
                self.style.ERROR(f'Split_Data.csv not found at {split_data_path}')
            )
            self.stdout.write('Please provide the correct path using --split-data option')
        
        self.stdout.write(self.style.SUCCESS('Reference data load complete!'))

    def load_split_data(self, file_path):
        """Load cost center split allocations"""
        self.stdout.write(f'Loading split data from {file_path}...')
        
        # Clear existing split data
        deleted_count = CostCenterSplit.objects.all().delete()[0]
        self.stdout.write(f'Cleared {deleted_count} existing split records')
        
        # Load new data
        loaded_count = 0
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            splits = []
            
            for row in reader:
                split = CostCenterSplit(
                    source_account=row['Cost Account'].strip(),
                    target_account=row['New Cost Account'].strip(),
                    percentage=float(row['Percentage']),
                    is_active=True
                )
                splits.append(split)
                loaded_count += 1
            
            # Bulk create for efficiency
            CostCenterSplit.objects.bulk_create(splits)
        
        self.stdout.write(
            self.style.SUCCESS(f'Loaded {loaded_count} cost center split rules')
        )
        
        # Show summary by source account
        self.stdout.write('\nSplit Summary:')
        source_accounts = CostCenterSplit.objects.values_list(
            'source_account', flat=True
        ).distinct()
        
        for source in source_accounts:
            count = CostCenterSplit.objects.filter(source_account=source).count()
            total_pct = sum(
                CostCenterSplit.objects.filter(source_account=source).values_list(
                    'percentage', flat=True
                )
            )
            self.stdout.write(f'  {source}: {count} targets, Total: {total_pct*100:.1f}%')