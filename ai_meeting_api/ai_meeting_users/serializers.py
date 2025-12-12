from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from ai_meeting_commons.exceptions import (
    BadRequestException,
    ConflictException,
    ErrorCode,
    NotFoundException,
    UnauthorizedException,
)

User = get_user_model()


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "password_confirm", "gender", "birth_date", "phone_number"]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise ConflictException("This email is already in use.", error_code=ErrorCode.EMAIL_ALREADY_EXISTS)
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise ConflictException("This username is already in use.", error_code=ErrorCode.USERNAME_ALREADY_EXISTS)
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise BadRequestException("Passwords do not match.", error_code=ErrorCode.PASSWORDS_DO_NOT_MATCH)
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        user = User.objects.create_user(**validated_data)
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise NotFoundException(
                "User with this email does not exist.", error_code=ErrorCode.USER_NOT_FOUND
            ) from None

        if not user.check_password(password):
            raise UnauthorizedException("Invalid password.", error_code=ErrorCode.INVALID_PASSWORD)

        if not user.is_active:
            raise UnauthorizedException("User account is disabled.", error_code=ErrorCode.ACCOUNT_DISABLED)

        attrs["user"] = user
        return attrs

    def get_tokens(self, user):
        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


class EmailCheckSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise ConflictException("This email is already in use.", error_code=ErrorCode.EMAIL_ALREADY_EXISTS)
        return value


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "gender", "birth_date", "phone_number", "created_at"]
        read_only_fields = ["id", "username", "email", "created_at"]


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["phone_number"]


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise UnauthorizedException("Current password is incorrect.", error_code=ErrorCode.INVALID_CURRENT_PASSWORD)
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise BadRequestException("New passwords do not match.", error_code=ErrorCode.PASSWORDS_DO_NOT_MATCH)
        return attrs

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user
