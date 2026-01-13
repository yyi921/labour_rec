"""
Load CostCenterSplit fixture into database
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Load CostCenterSplit fixture into database'

    def handle(self, *args, **options):
        self.stdout.write('Loading CostCenterSplit fixture...')

        try:
            call_command('loaddata', 'costcentersplit_fixture.json', verbosity=2)
            self.stdout.write(self.style.SUCCESS('✓ Successfully loaded CostCenterSplit data'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error loading fixture: {e}'))
            raise
