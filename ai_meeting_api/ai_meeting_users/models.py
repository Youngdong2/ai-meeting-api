from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("Username is required")
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    birth_date = models.DateField()
    phone_number = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Team 관련 필드
    team = models.ForeignKey(
        "ai_meeting_teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="members"
    )
    is_team_admin = models.BooleanField(default=False)  # 팀 관리자 여부

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email", "gender", "birth_date", "phone_number"]

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.username
