from django.urls import path

from . import views_account as a, views_auth as au, views_cart as c, views_catalog as cat, views_checkout as co, views_loop as lp

app_name = 'storefront'

urlpatterns = [
    path('', cat.HomeView.as_view(), name='home'),
    path('products/', cat.ProductListView.as_view(), name='product-list'),
    path('products/filters/', cat.FiltersSheetView.as_view(), name='filters-sheet'),
    path('search/', cat.SearchView.as_view(), name='search'),
    path('product/<slug:slug>/', cat.ProductDetailView.as_view(), name='product-detail'),
    path('emi/<int:variant_id>/', cat.EmiView.as_view(), name='emi'),

    path('cart/', c.CartView.as_view(), name='cart'),
    path('cart/badge/', c.CartBadgeView.as_view(), name='cart-badge'),
    path('cart/add/', c.CartAddView.as_view(), name='cart-add'),
    path('cart/update/', c.CartUpdateView.as_view(), name='cart-update'),
    path('cart/remove/<int:variant_id>/', c.CartRemoveView.as_view(), name='cart-remove'),

    path('checkout/', co.CheckoutView.as_view(), name='checkout'),
    path('checkout/address/', co.AddressPickerView.as_view(), name='checkout-address'),
    path('checkout/pay/', co.PayView.as_view(), name='pay'),
    path('checkout/pay/confirm/', co.PayConfirmView.as_view(), name='pay-confirm'),
    path('order/confirmation/<str:number>/', co.OrderConfirmationView.as_view(), name='order-confirmation'),

    path('modal/login/', au.LoginModalView.as_view(), name='login-modal'),
    path('modal/signup/', au.SignupModalView.as_view(), name='signup-modal'),
    path('modal/logout/', au.LogoutView.as_view(), name='logout'),
    path('modal/area/', au.AreaModalView.as_view(), name='area'),
    path('modal/schedule/', au.ScheduleModalView.as_view(), name='schedule'),
    path('delivery/speed/', au.SpeedView.as_view(), name='speed'),
    path('newsletter/', au.NewsletterView.as_view(), name='newsletter'),
    path('loop/remind/', lp.LoopRemindView.as_view(), name='loop-remind'),
    path('loop/add/', lp.LoopAddView.as_view(), name='loop-add'),
    path('loop/picker/<str:slot>/', lp.LoopPickerView.as_view(), name='loop-picker'),
    path('loop/pick/', lp.LoopPickView.as_view(), name='loop-pick'),
    path('loop/unpick/', lp.LoopUnpickView.as_view(), name='loop-unpick'),

    path('account/', a.AccountHomeView.as_view(), name='account'),
    path('account/orders/', a.OrderListView.as_view(), name='orders'),
    path('account/orders/<str:number>/', a.OrderDetailView.as_view(), name='order-detail'),
    path('account/orders/<str:number>/reorder/', a.ReorderView.as_view(), name='reorder'),
    path('account/invoice/<str:invoice>/', a.InvoiceView.as_view(), name='invoice'),
    path('account/addresses/', a.AddressListView.as_view(), name='addresses'),
    path('account/addresses/new/', a.AddressFormView.as_view(), name='address-new'),
    path('account/addresses/<int:pk>/edit/', a.AddressFormView.as_view(), name='address-edit'),
    path('account/addresses/<int:pk>/delete/', a.AddressDeleteView.as_view(), name='address-delete'),
    path('account/subscriptions/', a.SubscriptionListView.as_view(), name='subscriptions'),
    path('subscribe/<int:variant_id>/', a.SubscribeView.as_view(), name='subscribe'),
    path('account/subscriptions/<int:pk>/pause/', a.SubscriptionActionView.as_view(action='pause'), name='sub-pause'),
    path('account/subscriptions/<int:pk>/resume/', a.SubscriptionActionView.as_view(action='resume'), name='sub-resume'),
    path('account/subscriptions/<int:pk>/frequency/', a.SubscriptionActionView.as_view(action='frequency'), name='sub-frequency'),
    path('account/subscriptions/<int:pk>/cancel/', a.SubscriptionActionView.as_view(action='cancel'), name='sub-cancel'),
    path('account/details/', au.ProfileModalView.as_view(), name='details'),
    path('account/password/', au.PasswordModalView.as_view(), name='password'),
]
