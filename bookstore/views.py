from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from .models import Book, Order, OrderItem, Customer, Payment, Cart, CartItem, Coupon, CouponUsage, ContactMessage
from decimal import Decimal
import json
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
import re
from django.views.decorators.http import require_http_methods
from functools import wraps

# ============================================
# CUSTOM DECORATOR FOR CUSTOMER-ONLY VIEWS
# ============================================
def customer_required(view_func):
    """
    Decorator to ensure only users with Customer profiles can access the view.
    Redirects admin/staff users to admin panel with a message.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        # Check if user is admin/staff
        if request.user.is_staff or request.user.is_superuser:
            messages.warning(request, 'This feature is for customers only. Please use the admin panel.')
            return redirect('/admin/')
        
        # Check if user has a Customer profile
        if not hasattr(request.user, 'customer'):
            messages.error(request, 'Customer profile not found. Please contact support.')
            return redirect('home')
        
        return view_func(request, *args, **kwargs)
    return wrapper

# Authentication Views
def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        
        # Validation
        if password != password_confirm:
            messages.error(request, 'Passwords do not match!')
            return redirect('register')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists!')
            return redirect('register')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered!')
            return redirect('register')
        
        # Create User and Customer
        user = User.objects.create_user(username=username, email=email, password=password)
        customer = Customer.objects.create(user=user, phone=phone, address=address, is_first_time_buyer=True)
        
        Cart.objects.create(customer=customer)
        messages.success(request, 'Account created successfully! Please login.')
        return redirect('login')
    
    return render(request, 'bookstore/register.html')


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {username}!')
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password!')
            return redirect('login')
    
    return render(request, 'bookstore/login.html')


def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully!')
    return redirect('home')


# Main Pages
def home_page(request):
    return render(request, 'bookstore/home.html')


def book_list(request):
    # Get search query from GET parameters
    search_query = request.GET.get('search', '').strip()
    
    # Start with all books
    books = Book.objects.all()
    
    # Apply search filter if query exists
    if search_query:
        books = books.filter(
            Q(title__icontains=search_query) |
            Q(author__icontains=search_query) |
            Q(category__icontains=search_query) |
            Q(isbn__icontains=search_query)
        )
    
    context = {
        'books': books,
        'search_query': search_query,
    }
    
    return render(request, 'bookstore/book_list.html', context)


def book_detail(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    return render(request, 'bookstore/book_detail.html', {'book': book})


@login_required(login_url='login')
def order_history(request):
    customer = request.user.customer
    orders = Order.objects.filter(customer=customer)
    return render(request, 'bookstore/order_history.html', {'orders': orders})


def about_page(request):
    return render(request, 'bookstore/about.html')


def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone', '').strip() or None
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Save to database
        ContactMessage.objects.create(
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            message=message
        )
        
        messages.success(request, 'Thank you! Your message has been sent.')
        return redirect('contact')
    
    return render(request, 'bookstore/contact.html')


# Cart Management
@customer_required
def add_to_cart(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    customer = request.user.customer
    
    cart, created = Cart.objects.get_or_create(customer=customer)
    cart_item, created = CartItem.objects.get_or_create(cart=cart, book=book)
    
    if not created:
        if cart_item.quantity < book.stock:
            cart_item.quantity += 1
            cart_item.save()
            messages.success(request, f"Increased quantity of '{book.title}' in cart!")
        else:
            messages.warning(request, f"Cannot add more. Only {book.stock} in stock!")
    else:
        messages.success(request, f"'{book.title}' added to cart!")
    
    return redirect('view_cart')


@customer_required
def view_cart(request):
    customer = request.user.customer
    cart, created = Cart.objects.get_or_create(customer=customer)
    cart_items = cart.cartitem_set.all()
    
    context = {
        'cart': cart,
        'cart_items': cart_items,
    }
    return render(request, 'bookstore/cart.html', context)


@customer_required
def apply_coupon(request):
    if request.method == 'POST':
        coupon_code = request.POST.get('coupon_code', '').strip().upper()
        customer = request.user.customer
        cart = get_object_or_404(Cart, customer=customer)
        
        if not coupon_code:
            messages.error(request, 'Please enter a coupon code!')
            return redirect('view_cart')
        
        try:
            coupon = Coupon.objects.get(code=coupon_code)
        except Coupon.DoesNotExist:
            messages.error(request, 'Invalid coupon code!')
            return redirect('view_cart')
        
        # Validate coupon
        is_valid, msg = coupon.is_valid()
        if not is_valid:
            messages.error(request, f"Coupon error: {msg}")
            return redirect('view_cart')
        
        # Check minimum purchase
        if cart.subtotal < coupon.min_purchase:
            messages.error(request, f'Minimum purchase of Rs. {coupon.min_purchase} required for this coupon!')
            return redirect('view_cart')
        
        # Apply coupon
        cart.applied_coupon = coupon
        cart.save()
        
        discount_amount = coupon.calculate_discount(cart.subtotal)
        messages.success(request, f'Coupon "{coupon_code}" applied! You saved Rs. {discount_amount:.2f}')
        return redirect('view_cart')
    
    return redirect('view_cart')


@customer_required
def remove_coupon(request):
    if request.method == 'POST':
        customer = request.user.customer
        cart = get_object_or_404(Cart, customer=customer)
        
        if cart.applied_coupon:
            coupon_code = cart.applied_coupon.code
            cart.applied_coupon = None
            cart.save()
            messages.success(request, f'Coupon "{coupon_code}" removed!')
        else:
            messages.warning(request, 'No coupon applied!')
        
        return redirect('view_cart')
    
    return redirect('view_cart')


@customer_required
def update_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__customer=request.user.customer)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'increase':
            if cart_item.quantity < cart_item.book.stock:
                cart_item.quantity += 1
                cart_item.save()
                messages.success(request, 'Quantity updated!')
            else:
                messages.warning(request, 'Maximum stock reached!')
        
        elif action == 'decrease':
            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
                messages.success(request, 'Quantity updated!')
            else:
                messages.warning(request, 'Minimum quantity is 1!')
    
    return redirect('view_cart')


@customer_required
def remove_from_cart(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__customer=request.user.customer)
    book_title = cart_item.book.title
    cart_item.delete()
    messages.success(request, f"'{book_title}' removed from cart!")
    return redirect('view_cart')

@customer_required
def edit_profile(request):
    customer = request.user.customer
    
    if request.method == 'POST':
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        
        request.user.email = email
        request.user.save()
        
        customer.phone = phone
        customer.address = address
        customer.save()
        
        messages.success(request, 'Profile updated successfully!')
        return redirect('edit_profile')
    
    return render(request, 'bookstore/edit_profile.html', {'customer': customer})


@customer_required
def cancel_order(request, order_id):
    """
    Cancel an order if it's in a cancellable state (Pending or Confirmed)
    and restore stock for all items
    """
    order = get_object_or_404(Order, id=order_id, customer=request.user.customer)
    
    # Check if order can be cancelled
    cancellable_statuses = ['Pending', 'Confirmed']
    if order.status not in cancellable_statuses:
        messages.error(request, f"Cannot cancel order in '{order.status}' status!")
        return redirect('order_history')
    
    if request.method == 'POST':
        cancellation_reason = request.POST.get('cancellation_reason', '').strip()
        
        # Restore stock for all items in the order
        for order_item in order.orderitem_set.all():
            order_item.book.stock += order_item.quantity
            order_item.book.save()
        
        # Revert coupon usage if coupon was applied
        if order.applied_coupon:
            order.applied_coupon.current_usage -= 1
            order.applied_coupon.save()
            
            # Delete coupon usage record
            CouponUsage.objects.filter(order=order).delete()
        
        # Update order status and save cancellation details
        order.status = 'Cancelled'
        order.cancellation_reason = cancellation_reason if cancellation_reason else None
        order.cancelled_at = timezone.now()
        order.save()
        
        messages.success(
            request, 
            f'Order #{order.id} cancelled successfully! Stock has been restored.'
        )
        return redirect('order_history')
    
    context = {
        'order': order,
    }
    return render(request, 'bookstore/cancel_order.html', context)

@customer_required
def change_password(request):
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        user = request.user
        
        # Validate current password
        if not user.check_password(current_password):
            messages.error(request, 'Current password is incorrect!')
            return redirect('change_password')
        
        # Check if new passwords match
        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match!')
            return redirect('change_password')
        
        # Check password length
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long!')
            return redirect('change_password')
        
        # Update password
        user.set_password(new_password)
        user.save()
        
        # Keep user logged in after password change
        update_session_auth_hash(request, user)
        
        messages.success(request, 'Password changed successfully!')
        return redirect('edit_profile')
    
    return render(request, 'bookstore/change_password.html')

# Card Payment Validation Functions
def validate_card_number(card_number):
    """Validate card number using Luhn algorithm"""
    # Remove spaces
    card_number = card_number.replace(' ', '')
    
    # Check if it's only digits
    if not card_number.isdigit():
        return False, "Card number must contain only digits"
    
    # Check length (most cards are 13-19 digits)
    if len(card_number) < 13 or len(card_number) > 19:
        return False, "Card number must be between 13-19 digits"
    
    # Luhn Algorithm
    def luhn_check(num):
        total = 0
        reverse_digits = num[::-1]
        for i, digit in enumerate(reverse_digits):
            n = int(digit)
            if i % 2 == 1:
                n = n * 2
                if n > 9:
                    n = n - 9
            total += n
        return total % 10 == 0
    
    if not luhn_check(card_number):
        return False, "Invalid card number (failed Luhn check)"
    
    return True, "Valid"


def validate_expiry_date(month, year):
    """Validate expiry date"""
    try:
        month = int(month)
        year = int(year)
    except:
        return False, "Invalid expiry format"
    
    if month < 1 or month > 12:
        return False, "Month must be between 01-12"
    
    # Convert 2-digit year to 4-digit
    if year < 100:
        current_year = timezone.now().year
        current_century = (current_year // 100) * 100
        year = current_century + year
    
    current_date = timezone.now()
    current_year = current_date.year
    current_month = current_date.month
    
    # Check if card is expired
    if year < current_year:
        return False, "Card has expired"
    
    if year == current_year and month < current_month:
        return False, "Card has expired"
    
    return True, "Valid"


def validate_cvv(cvv):
    """Validate CVV"""
    if not cvv.isdigit():
        return False, "CVV must contain only digits"
    
    if len(cvv) not in [3, 4]:
        return False, "CVV must be 3 or 4 digits"
    
    return True, "Valid"


def get_card_type(card_number):
    """Determine card type from card number"""
    card_number = card_number.replace(' ', '')
    
    patterns = {
        'Visa': r'^4[0-9]{12}(?:[0-9]{3})?$',
        'Mastercard': r'^5[1-5][0-9]{14}$',
        'American Express': r'^3[47][0-9]{13}$',
        'Discover': r'^6(?:011|5[0-9]{2})[0-9]{12}$',
    }
    
    for card_type, pattern in patterns.items():
        if re.match(pattern, card_number):
            return card_type
    
    return 'Unknown'


# Card Payment Views
@customer_required
def card_payment_form(request):
    """Display card payment form"""
    customer = request.user.customer
    cart = get_object_or_404(Cart, customer=customer)
    cart_items = cart.cartitem_set.all()
    
    if not cart_items:
        messages.warning(request, 'Your cart is empty!')
        return redirect('view_cart')
    
    # Get delivery details from POST data (passed from checkout form)
    delivery_name = request.POST.get('delivery_name', customer.user.get_full_name() or customer.user.username)
    delivery_phone = request.POST.get('delivery_phone', customer.phone)
    delivery_address = request.POST.get('delivery_address', customer.address)
    delivery_notes = request.POST.get('delivery_notes', '')
    
    context = {
        'cart': cart,
        'cart_items': cart_items,
        'customer': customer,
        'delivery_name': delivery_name,
        'delivery_phone': delivery_phone,
        'delivery_address': delivery_address,
        'delivery_notes': delivery_notes,
    }
    
    return render(request, 'bookstore/card_payment_form.html', context)


@customer_required
@require_http_methods(["POST"])
def process_card_payment(request):
    """Process card payment and create order"""
    customer = request.user.customer
    cart = get_object_or_404(Cart, customer=customer)
    cart_items = cart.cartitem_set.all()
    
    if not cart_items:
        return JsonResponse({'success': False, 'message': 'Cart is empty'})
    
    # Get card details from form
    card_number = request.POST.get('card_number', '').strip()
    card_holder = request.POST.get('card_holder', '').strip()
    expiry_month = request.POST.get('expiry_month', '').strip()
    expiry_year = request.POST.get('expiry_year', '').strip()
    cvv = request.POST.get('cvv', '').strip()
    
    # Get delivery details from session/post
    delivery_name = request.POST.get('delivery_name', '').strip()
    delivery_phone = request.POST.get('delivery_phone', '').strip()
    delivery_address = request.POST.get('delivery_address', '').strip()
    delivery_notes = request.POST.get('delivery_notes', '').strip() or None
    
    # Validate all fields are provided
    if not all([card_number, card_holder, expiry_month, expiry_year, cvv, 
                delivery_name, delivery_phone, delivery_address]):
        return JsonResponse({
            'success': False,
            'message': 'All fields are required'
        })
    
    # Validate card number
    is_valid, msg = validate_card_number(card_number)
    if not is_valid:
        return JsonResponse({'success': False, 'message': msg})
    
    # Validate expiry date
    is_valid, msg = validate_expiry_date(expiry_month, expiry_year)
    if not is_valid:
        return JsonResponse({'success': False, 'message': msg})
    
    # Validate CVV
    is_valid, msg = validate_cvv(cvv)
    if not is_valid:
        return JsonResponse({'success': False, 'message': msg})
    
    # Validate card holder name
    if len(card_holder) < 3:
        return JsonResponse({
            'success': False,
            'message': 'Card holder name must be at least 3 characters'
        })
    
    try:
        # All validations passed - Create Order
        order = Order.objects.create(
            customer=customer,
            delivery_name=delivery_name,
            delivery_phone=delivery_phone,
            delivery_address=delivery_address,
            delivery_notes=delivery_notes,
            shipping_fee=cart.shipping_fee,
            applied_coupon=cart.applied_coupon,
            coupon_discount=cart.coupon_discount,
            order_value_discount=cart.order_value_discount,
            first_time_discount=cart.first_time_discount,
            discount_code_used=cart.applied_coupon.code if cart.applied_coupon else None
        )
        
        # Create Order Items
        for cart_item in cart_items:
            OrderItem.objects.create(
                order=order,
                book=cart_item.book,
                quantity=cart_item.quantity,
                unit_price=cart_item.book.price,
                subtotal=cart_item.subtotal
            )
        
        # Update Coupon Usage
        if cart.applied_coupon:
            from .models import CouponUsage
            coupon = cart.applied_coupon
            coupon.current_usage += 1
            coupon.save()
            
            CouponUsage.objects.create(
                coupon=coupon,
                customer=customer,
                order=order
            )
        
        # Update First-Time Buyer Status
        if customer.is_first_time_buyer:
            customer.is_first_time_buyer = False
            customer.save()
        
        # Create Payment with Card Details
        card_type = get_card_type(card_number)
        masked_card = '**** **** **** ' + card_number[-4:]
        
        Payment.objects.create(
            order=order,
            amount=order.total_amount,
            method='Card',
            status='Paid',
            transaction_id=f"CARD-{order.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        )
        
        # Store payment details in session for confirmation page
        request.session['payment_details'] = {
            'card_type': card_type,
            'masked_card': masked_card,
            'card_holder': card_holder,
            'transaction_id': f"CARD-{order.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
        }
        
        # Clear Cart
        cart_items.delete()
        cart.applied_coupon = None
        cart.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Payment processed successfully!',
            'order_id': order.id,
            'redirect_url': f'/orders/{order.id}/payment-success/'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error processing payment: {str(e)}'
        })


@customer_required
def payment_success(request, order_id):
    """Display payment success page"""
    order = get_object_or_404(Order, id=order_id, customer=request.user.customer)
    payment = get_object_or_404(Payment, order=order)
    payment_details = request.session.get('payment_details', {})
    
    # Clear session data
    if 'payment_details' in request.session:
        del request.session['payment_details']
    request.session.modified = True
    
    context = {
        'order': order,
        'payment': payment,
        'payment_details': payment_details,
    }
    
    return render(request, 'bookstore/payment_success.html', context)


@customer_required
def payment_failed(request):
    """Display payment failed page"""
    return render(request, 'bookstore/payment_failed.html')


# Update checkout view to handle card payment
@customer_required
def checkout(request):
    customer = request.user.customer
    cart = get_object_or_404(Cart, customer=customer)
    cart_items = cart.cartitem_set.all()
    
    if not cart_items:
        messages.warning(request, 'Your cart is empty!')
        return redirect('view_cart')
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'Cash')
        delivery_name = request.POST.get('delivery_name')
        delivery_phone = request.POST.get('delivery_phone')
        delivery_address = request.POST.get('delivery_address')
        delivery_notes = request.POST.get('delivery_notes', '')
        
        # Validate delivery details
        if not all([delivery_name, delivery_phone, delivery_address]):
            messages.error(request, 'Please fill in all delivery details!')
            return redirect('checkout')
        
        # Store delivery details in session
        request.session['delivery_name'] = delivery_name
        request.session['delivery_phone'] = delivery_phone
        request.session['delivery_address'] = delivery_address
        request.session['delivery_notes'] = delivery_notes
        
        # If Cash payment, create order directly
        if payment_method == 'Cash':
            try:
                order = Order.objects.create(
                    customer=customer,
                    delivery_name=delivery_name,
                    delivery_phone=delivery_phone,
                    delivery_address=delivery_address,
                    delivery_notes=delivery_notes,
                    shipping_fee=cart.shipping_fee,
                    applied_coupon=cart.applied_coupon,
                    coupon_discount=cart.coupon_discount,
                    order_value_discount=cart.order_value_discount,
                    first_time_discount=cart.first_time_discount,
                    discount_code_used=cart.applied_coupon.code if cart.applied_coupon else None
                )
                
                # Create Order Items
                for cart_item in cart_items:
                    OrderItem.objects.create(
                        order=order,
                        book=cart_item.book,
                        quantity=cart_item.quantity,
                        unit_price=cart_item.book.price,
                        subtotal=cart_item.subtotal
                    )
                
                # Update Coupon Usage
                if cart.applied_coupon:
                    from .models import CouponUsage
                    coupon = cart.applied_coupon
                    coupon.current_usage += 1
                    coupon.save()
                    
                    CouponUsage.objects.create(
                        coupon=coupon,
                        customer=customer,
                        order=order
                    )
                
                # Update First-Time Buyer Status
                if customer.is_first_time_buyer:
                    customer.is_first_time_buyer = False
                    customer.save()
                
                # Create Payment (Unpaid for Cash)
                Payment.objects.create(
                    order=order,
                    amount=order.total_amount,
                    method=payment_method,
                    status='Unpaid'
                )
                
                # Clear Cart
                cart_items.delete()
                cart.applied_coupon = None
                cart.save()
                
                messages.success(request, f'Order #{order.id} placed successfully! You saved Rs. {order.total_discount:.2f}')
                return redirect('order_history')
            
            except Exception as e:
                messages.error(request, f'Error creating order: {str(e)}')
                return redirect('checkout')
        
        # If Card payment, redirect to card payment form with POST data
        elif payment_method == 'Card':
            # Instead of just redirecting, we'll render the card form directly with data
            return card_payment_form(request)
        
        else:
            messages.error(request, 'Invalid payment method!')
            return redirect('checkout')
    
    context = {
        'cart': cart,
        'cart_items': cart_items,
        'customer': customer,
    }
    return render(request, 'bookstore/checkout.html', context)