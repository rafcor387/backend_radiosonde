import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Person',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('paternal_surname', models.CharField(max_length=100)),
                ('maternal_surname', models.CharField(max_length=100)),
                ('email', models.EmailField(max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, null=True)),
            ],
            options={
                'db_table': 'persons',
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(max_length=20, unique=True)),
                ('token_version', models.PositiveIntegerField(default=1)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('is_staff', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
                ('person', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='user', to='usuarios.person')),
            ],
            options={
                'db_table': 'users',
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='PersonRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(choices=[('STUDENT', 'Student'), ('INTERN', 'Intern'), ('TEACHER', 'Teacher'), ('ASSISTANT', 'Assistant')], max_length=30, unique=True)),
                ('name', models.CharField(max_length=50, unique=True)),
            ],
            options={
                'db_table': 'person_roles',
                'ordering': ['id'],
                'constraints': [models.CheckConstraint(condition=models.Q(('code__in', ['STUDENT', 'INTERN', 'TEACHER', 'ASSISTANT'])), name='person_role_code_valid'), models.CheckConstraint(condition=models.Q(('name', ''), _negated=True), name='person_role_name_not_empty')],
            },
        ),
        migrations.AddField(
            model_name='person',
            name='person_role',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='persons', to='usuarios.personrole'),
        ),
        migrations.CreateModel(
            name='Invitation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('CANCELLED', 'Cancelled'), ('ACCEPTED', 'Accepted'), ('EXPIRED', 'Expired')], default='PENDING', max_length=15)),
                ('expires_at', models.DateTimeField()),
                ('accepted_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('accepted_user', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='accepted_invitation', to=settings.AUTH_USER_MODEL)),
                ('invited_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sent_invitations', to=settings.AUTH_USER_MODEL)),
                ('person_role', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='invitations', to='usuarios.personrole')),
            ],
            options={
                'db_table': 'invitations',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='UserRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(choices=[('ADMINISTRATOR', 'Administrator'), ('USER', 'User')], max_length=30, unique=True)),
                ('name', models.CharField(max_length=50, unique=True)),
            ],
            options={
                'db_table': 'user_roles',
                'ordering': ['id'],
                'constraints': [models.CheckConstraint(condition=models.Q(('code__in', ['ADMINISTRATOR', 'USER'])), name='user_role_code_valid'), models.CheckConstraint(condition=models.Q(('name', ''), _negated=True), name='user_role_name_not_empty')],
            },
        ),
        migrations.AddField(
            model_name='user',
            name='user_role',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='users', to='usuarios.userrole'),
        ),
        migrations.AddConstraint(
            model_name='person',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('email'), name='person_email_case_insensitive_unique'),
        ),
        migrations.AddConstraint(
            model_name='person',
            constraint=models.CheckConstraint(condition=models.Q(('name', ''), _negated=True), name='person_name_not_empty'),
        ),
        migrations.AddConstraint(
            model_name='person',
            constraint=models.CheckConstraint(condition=models.Q(('paternal_surname', ''), _negated=True), name='person_paternal_surname_not_empty'),
        ),
        migrations.AddConstraint(
            model_name='person',
            constraint=models.CheckConstraint(condition=models.Q(('maternal_surname', ''), _negated=True), name='person_maternal_surname_not_empty'),
        ),
        migrations.AddConstraint(
            model_name='person',
            constraint=models.CheckConstraint(condition=models.Q(('email', ''), _negated=True), name='person_email_not_empty'),
        ),
        migrations.AddIndex(
            model_name='invitation',
            index=models.Index(fields=['status', 'expires_at'], name='invitation_status_expiry_idx'),
        ),
        migrations.AddConstraint(
            model_name='invitation',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('email'), condition=models.Q(('status', 'PENDING')), name='one_pending_invitation_per_email'),
        ),
        migrations.AddConstraint(
            model_name='invitation',
            constraint=models.CheckConstraint(condition=models.Q(('email', ''), _negated=True), name='invitation_email_not_empty'),
        ),
        migrations.AddConstraint(
            model_name='invitation',
            constraint=models.CheckConstraint(condition=models.Q(('expires_at__gt', models.F('created_at'))), name='invitation_expiry_after_creation'),
        ),
        migrations.AddConstraint(
            model_name='invitation',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('accepted_at__isnull', False), ('accepted_user__isnull', False), ('cancelled_at__isnull', True), ('status', 'ACCEPTED')), models.Q(('accepted_at__isnull', True), ('accepted_user__isnull', True), ('cancelled_at__isnull', False), ('status', 'CANCELLED')), models.Q(('accepted_at__isnull', True), ('accepted_user__isnull', True), ('cancelled_at__isnull', True), ('status__in', ['PENDING', 'EXPIRED'])), _connector='OR'), name='invitation_status_dates_consistent'),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('username'), name='user_username_case_insensitive_unique'),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(condition=models.Q(('username', ''), _negated=True), name='user_username_not_empty'),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(condition=models.Q(('token_version__gte', 1)), name='user_token_version_positive'),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(condition=models.Q(('deleted_at__isnull', True), ('is_active', False), _connector='OR'), name='deleted_user_must_be_inactive'),
        ),
    ]
