from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ai_meeting_commons.permissions import IsOwner
from .serializers import (
    EmailCheckSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    ProfileUpdateSerializer,
    SignupSerializer,
    UserSerializer,
)

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action in ['signup', 'login', 'check_email']:
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'signup':
            return SignupSerializer
        if self.action == 'login':
            return LoginSerializer
        if self.action == 'check_email':
            return EmailCheckSerializer
        if self.action == 'update_profile':
            return ProfileUpdateSerializer
        if self.action == 'change_password':
            return PasswordChangeSerializer
        return UserSerializer

    @action(detail=False, methods=['post'], url_path='auth/signup')
    def signup(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {'message': 'User created successfully.', 'user_id': user.id},
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=['post'], url_path='auth/login')
    def login(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        tokens = serializer.get_tokens(user)
        return Response({
            'message': 'Login successful.',
            'tokens': tokens,
            'user': UserSerializer(user).data,
        })

    @action(detail=False, methods=['post'], url_path='auth/check-email')
    def check_email(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({'message': 'Email is available.'})

    @action(detail=False, methods=['get'], url_path='profile/me')
    def me(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=['patch'], url_path='profile/update')
    def update_profile(self, request):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'message': 'Profile updated successfully.',
            'user': UserSerializer(request.user).data,
        })

    @action(detail=False, methods=['post'], url_path='profile/change-password')
    def change_password(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password changed successfully.'})
