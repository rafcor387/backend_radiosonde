from django.urls import path
from .views import RadiosondeProcessView, RadiosondeProfileView, RadiosondeSearchView

urlpatterns = [
    path('radiosondes/search/', RadiosondeSearchView.as_view(), name='radiosonde-search'),
    path(
        'radiosondes/<int:profile_id>/profile/',
        RadiosondeProfileView.as_view(),
        name='radiosonde-profile',
    ),
    path('process/', RadiosondeProcessView.as_view(), name='radiosonde-process'),
]
