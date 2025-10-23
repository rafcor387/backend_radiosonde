from django.urls import path
from .views import RadiosondeProcessView

urlpatterns = [
    path('process/', RadiosondeProcessView.as_view(), name='radiosonde-process'),
]