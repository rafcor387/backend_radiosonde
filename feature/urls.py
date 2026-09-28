from django.urls import path
from .views import RadiosondeProcessView, RadiosondeSearchView

urlpatterns = [
    path('radiosondes/search/', RadiosondeSearchView.as_view(), name='radiosonde-search'),
    path('process/', RadiosondeProcessView.as_view(), name='radiosonde-process'),
]
