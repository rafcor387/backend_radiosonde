from django.urls import path
from .views import (
    RadiosondeProcessView,
    RadiosondeHodographImageView,
    RadiosondeHodographView,
    RadiosondeProfileView,
    RadiosondeSearchView,
    RadiosondeSkewTImageView,
    RadiosondeSkewTView,
    RadiosondeStabilityView,
)

urlpatterns = [
    path('radiosondes/search/', RadiosondeSearchView.as_view(), name='radiosonde-search'),
    path(
        'radiosondes/<int:profile_id>/profile/',
        RadiosondeProfileView.as_view(),
        name='radiosonde-profile',
    ),
    path(
        'radiosondes/<int:profile_id>/stability/',
        RadiosondeStabilityView.as_view(),
        name='radiosonde-stability',
    ),
    path(
        'radiosondes/<int:profile_id>/skew-t/',
        RadiosondeSkewTView.as_view(),
        name='radiosonde-skew-t',
    ),
    path(
        'radiosondes/<int:profile_id>/skew-t/image/',
        RadiosondeSkewTImageView.as_view(),
        name='radiosonde-skew-t-image',
    ),
    path(
        'radiosondes/<int:profile_id>/hodograph/',
        RadiosondeHodographView.as_view(),
        name='radiosonde-hodograph',
    ),
    path(
        'radiosondes/<int:profile_id>/hodograph/image/',
        RadiosondeHodographImageView.as_view(),
        name='radiosonde-hodograph-image',
    ),
    path('process/', RadiosondeProcessView.as_view(), name='radiosonde-process'),
]
