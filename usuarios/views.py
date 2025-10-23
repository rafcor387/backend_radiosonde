from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from .serializers import LoginSerializer
from rest_framework.permissions import IsAuthenticated


class LoginView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            tokens = serializer.save()
            return Response(tokens, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class MeView(APIView):  # <- Asegúrate del ":" aquí
    permission_classes = [IsAuthenticated]  # <- 4 espacios dentro de la clase

    def get(self, request):
        user = request.user
        return Response({"username": user.username}, status=status.HTTP_200_OK)
