from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema

from usuarios.models import User
from usuarios.serializers import UserSerializer

class UserMeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request):
        serializer = self.serializer_class(request.user)
        return Response(serializer.data)

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    @extend_schema(responses={200: UserSerializer(many=True)})
    def get(self, request, user_id=None):
        if user_id is None:
            if not request.user.is_staff:
                return Response({'error': 'No autorizado'}, status=status.HTTP_403_FORBIDDEN)
            users = User.objects.all().order_by('id')
            serializer = self.serializer_class(users, many=True)
            return Response(serializer.data)

        user = get_object_or_404(User, id=user_id)
        serializer = self.serializer_class(user)
        return Response(serializer.data)

    def patch(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ... podrías añadir PUT y DELETE siguiendo el mismo patrón ...