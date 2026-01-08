"""
Django management command to populate SageLocation and SageDepartment mappings.

Usage:
    python manage.py populate_mappings
    Or via Railway: railway run python manage.py populate_mappings
"""

from django.core.management.base import BaseCommand
from reconciliation.models import SageLocation, SageDepartment


class Command(BaseCommand):
    help = 'Populate SageLocation and SageDepartment mapping tables'

    def handle(self, *args, **options):
        # Location mappings
        locations = [
            {"location_id": "100", "location_name": "Breakwater Island Trust"},
            {"location_id": "421", "location_name": "Marmor"},
            {"location_id": "422", "location_name": "Terasu"},
            {"location_id": "423", "location_name": "Ardo Rooftop Bar"},
            {"location_id": "424", "location_name": "Ardo Pool Side Dining"},
            {"location_id": "425", "location_name": "Ville Container Chiller"},
            {"location_id": "426", "location_name": "Ardo Mini Bar"},
            {"location_id": "427", "location_name": "Ardo In Room Dining"},
            {"location_id": "428", "location_name": "Ardo Food Store"},
            {"location_id": "429", "location_name": "Ardo Beverage Store"},
            {"location_id": "430", "location_name": "Ardo Hotel"},
            {"location_id": "442", "location_name": "Sports Bar"},
            {"location_id": "444", "location_name": "Quarterdeck"},
            {"location_id": "446", "location_name": "Splash Bar"},
            {"location_id": "448", "location_name": "Magnetic Room Bar"},
            {"location_id": "449", "location_name": "Orpheus Room Bar"},
            {"location_id": "450", "location_name": "Palm House"},
            {"location_id": "454", "location_name": "Miss Songs"},
            {"location_id": "458", "location_name": "Spin"},
            {"location_id": "460", "location_name": "Event Operations"},
            {"location_id": "470", "location_name": "Gaming"},
            {"location_id": "480", "location_name": "The Ville Hotel"},
            {"location_id": "486", "location_name": "Mini Bar"},
            {"location_id": "488", "location_name": "Room Service"},
            {"location_id": "550", "location_name": "Ville Food Store"},
            {"location_id": "551", "location_name": "Ville Beverage Store"},
            {"location_id": "552", "location_name": "Ville General Store"},
            {"location_id": "553", "location_name": "Ville Container Freezer"},
            {"location_id": "600", "location_name": "Ardo (Saltwater)"},
            {"location_id": "700", "location_name": "TECC"},
            {"location_id": "910", "location_name": "Shared Services The Ville"},
        ]

        # Department mappings
        departments = [
            {"department_id": "1", "department_name": "Software"},
            {"department_id": "10", "department_name": "Finance & Administration"},
            {"department_id": "2", "department_name": "Services"},
            {"department_id": "20", "department_name": "Venue Management"},
            {"department_id": "21", "department_name": "Venue Management"},
            {"department_id": "22", "department_name": "Venue Management"},
            {"department_id": "25", "department_name": "Brewery"},
            {"department_id": "26", "department_name": "Brewery Sales Reps"},
            {"department_id": "27", "department_name": "Venue Management"},
            {"department_id": "3", "department_name": "Development"},
            {"department_id": "30", "department_name": "Beverage"},
            {"department_id": "4", "department_name": "Product Solutions"},
            {"department_id": "40", "department_name": "Engineering"},
            {"department_id": "41", "department_name": "Property Services"},
            {"department_id": "42", "department_name": "Security"},
            {"department_id": "43", "department_name": "Surveillance"},
            {"department_id": "44", "department_name": "Staff Accommodation"},
            {"department_id": "5", "department_name": "CS Team"},
            {"department_id": "50", "department_name": "Food"},
            {"department_id": "60", "department_name": "Functions and Events"},
            {"department_id": "62", "department_name": "Retail"},
            {"department_id": "63", "department_name": "Retail - Merchandise"},
            {"department_id": "65", "department_name": "EGM"},
            {"department_id": "66", "department_name": "Table Games"},
            {"department_id": "67", "department_name": "VIP Services"},
            {"department_id": "68", "department_name": "Cage"},
            {"department_id": "70", "department_name": "Accommodation"},
            {"department_id": "71", "department_name": "Housekeeping"},
            {"department_id": "72", "department_name": "Cleaners"},
            {"department_id": "73", "department_name": "Laundry"},
            {"department_id": "74", "department_name": "Reservations"},
            {"department_id": "75", "department_name": "Spa"},
            {"department_id": "80", "department_name": "Maintenance"},
            {"department_id": "85", "department_name": "Tourism"},
            {"department_id": "86", "department_name": "Commercial"},
            {"department_id": "87", "department_name": "General Aviation"},
            {"department_id": "90", "department_name": "Finance & Administration"},
            {"department_id": "91", "department_name": "Compliance"},
            {"department_id": "92", "department_name": "People & Culture"},
            {"department_id": "93", "department_name": "Stores"},
            {"department_id": "94", "department_name": "IT"},
            {"department_id": "95", "department_name": "Marketing"},
        ]

        # Populate locations
        self.stdout.write('Populating locations...')
        created_locations = 0
        updated_locations = 0

        for loc in locations:
            obj, created = SageLocation.objects.update_or_create(
                location_id=loc['location_id'],
                defaults={'location_name': loc['location_name']}
            )
            if created:
                created_locations += 1
            else:
                updated_locations += 1

        self.stdout.write(self.style.SUCCESS(
            f'Locations: Created {created_locations}, Updated {updated_locations}'
        ))

        # Populate departments
        self.stdout.write('Populating departments...')
        created_departments = 0
        updated_departments = 0

        for dept in departments:
            obj, created = SageDepartment.objects.update_or_create(
                department_id=dept['department_id'],
                defaults={'department_name': dept['department_name']}
            )
            if created:
                created_departments += 1
            else:
                updated_departments += 1

        self.stdout.write(self.style.SUCCESS(
            f'Departments: Created {created_departments}, Updated {updated_departments}'
        ))

        self.stdout.write(self.style.SUCCESS('✓ Mapping population complete!'))
