<?php
/**
 * نرمال‌ساز SKU محصولات تکسایدک
 * -------------------------------------------------------------------------
 * کد تدارکاتی ایساکو همیشه ۱۰ رقم است و صفرهای ابتدایی دارد (مثل 0050102699).
 * هنگام ورود اطلاعات به سایت، این صفرها در خیلی از محصولات حذف شده‌اند.
 * این اسکریپت همهٔ SKU های عددی را به فرم ۱۰ رقمی استاندارد برمی‌گرداند.
 *
 * نحوهٔ استفاده (فقط مدیر سایت):
 *   1) گزارش بدون تغییر :  /wp-admin/?texa_fix_sku=1
 *   2) اعمال تغییرات    :  /wp-admin/?texa_fix_sku=1&apply=1
 *   3) بازگرداندن       :  /wp-admin/?texa_fix_sku=revert
 *
 * قبل از اجرای حالت ۲ حتماً از دیتابیس بکاپ بگیرید.
 * SKU قبلی هر محصول در متای _texa_sku_before ذخیره می‌شود تا برگشت‌پذیر باشد.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/** طول استاندارد کد تدارکاتی ایساکو */
const TEXA_SKU_LEN = 10;

/** فقط SKU هایی با این طول‌ها پد می‌شوند؛ بقیه دست‌نخورده می‌مانند. */
const TEXA_SKU_PADDABLE = [ 8, 9, 10 ];

/**
 * یک SKU خام را به فرم استاندارد ۱۰ رقمی تبدیل می‌کند.
 *
 * - ارقام فارسی (۰۱۲) و عربی (٠١٢) را به انگلیسی تبدیل می‌کند
 * - فاصله، نیم‌فاصله، خط تیره و هر کاراکتر غیرعددی را حذف می‌کند
 * - با صفر از سمت چپ تا ۱۰ رقم پر می‌کند
 *
 * @param string $sku SKU خام
 * @return string SKU نرمال‌شده، یا رشتهٔ خالی اگر قابل نرمال‌سازی نباشد
 */
function texa_normalize_sku( $sku ) {
	$sku = (string) $sku;

	$fa = [ '۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹' ];
	$ar = [ '٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩' ];
	$en = [ '0', '1', '2', '3', '4', '5', '6', '7', '8', '9' ];

	$sku = str_replace( $fa, $en, $sku );
	$sku = str_replace( $ar, $en, $sku );

	// هر چیزی جز رقم حذف می‌شود (فاصله، نیم‌فاصله U+200C، خط تیره، حروف)
	$digits = preg_replace( '/\D+/u', '', $sku );

	if ( '' === $digits ) {
		return '';
	}

	// کدهای غیرایساکویی (مثلاً ۱۲ رقمی جهان‌پارت) دست‌نخورده می‌مانند
	if ( ! in_array( strlen( $digits ), TEXA_SKU_PADDABLE, true ) ) {
		return $digits;
	}

	return str_pad( $digits, TEXA_SKU_LEN, '0', STR_PAD_LEFT );
}

/**
 * نقطهٔ ورود: با پارامتر URL اجرا می‌شود.
 */
add_action( 'admin_init', 'texa_sku_normalizer_run' );
function texa_sku_normalizer_run() {
	if ( ! isset( $_GET['texa_fix_sku'] ) ) {
		return;
	}
	if ( ! current_user_can( 'manage_woocommerce' ) ) {
		wp_die( 'شما دسترسی لازم برای اجرای این ابزار را ندارید.' );
	}

	if ( 'revert' === $_GET['texa_fix_sku'] ) {
		texa_sku_revert();
		return;
	}

	$apply = isset( $_GET['apply'] ) && '1' === $_GET['apply'];
	texa_sku_report( $apply );
}

/**
 * گزارش می‌گیرد و در صورت درخواست، تغییرات را اعمال می‌کند.
 *
 * @param bool $apply اگر true باشد واقعاً می‌نویسد، وگرنه فقط گزارش می‌دهد.
 */
function texa_sku_report( $apply ) {
	global $wpdb;

	// خواندن مستقیم از دیتابیس؛ سریع‌تر و بدون بارگذاری کل آبجکت محصول
	$rows = $wpdb->get_results(
		"SELECT p.ID, p.post_title, p.post_type, pm.meta_value AS sku
		   FROM {$wpdb->posts} p
		   JOIN {$wpdb->postmeta} pm ON pm.post_id = p.ID AND pm.meta_key = '_sku'
		  WHERE p.post_type IN ('product','product_variation')
		    AND p.post_status != 'trash'
		  ORDER BY p.ID"
	);

	$plan       = [];  // ID => ['old'=>..,'new'=>..,'title'=>..]
	$unchanged  = 0;
	$empty      = 0;
	$target_map = [];  // SKU جدید => لیست IDها، برای کشف تداخل

	// SKU هایی که همین حالا روی سایت هستند (برای کشف تداخل با محصولات دست‌نخورده)
	$existing = [];
	foreach ( $rows as $r ) {
		$existing[ trim( (string) $r->sku ) ][] = (int) $r->ID;
	}

	foreach ( $rows as $r ) {
		$old = trim( (string) $r->sku );

		if ( '' === $old ) {
			$empty++;
			continue;
		}

		$new = texa_normalize_sku( $old );

		if ( '' === $new || $new === $old ) {
			$unchanged++;
			continue;
		}

		$plan[ (int) $r->ID ] = [
			'old'   => $old,
			'new'   => $new,
			'title' => $r->post_title,
		];
		$target_map[ $new ][] = (int) $r->ID;
	}

	// کشف تداخل: دو محصول که بعد از نرمال‌سازی SKU یکسان پیدا می‌کنند،
	// یا محصولی که SKU جدیدش با SKU فعلی یک محصول دیگر یکی می‌شود.
	$conflicts = [];
	foreach ( $target_map as $new_sku => $ids ) {
		$clash = $ids;
		if ( isset( $existing[ $new_sku ] ) ) {
			$clash = array_unique( array_merge( $clash, $existing[ $new_sku ] ) );
		}
		if ( count( $clash ) > 1 ) {
			$conflicts[ $new_sku ] = $clash;
			foreach ( $ids as $id ) {
				unset( $plan[ $id ] );   // محصولات متداخل هرگز نوشته نمی‌شوند
			}
		}
	}

	$applied = [];
	$failed  = [];

	if ( $apply ) {
		foreach ( $plan as $id => $info ) {
			$product = wc_get_product( $id );
			if ( ! $product ) {
				$failed[ $id ] = 'محصول یافت نشد';
				continue;
			}
			try {
				// SKU قبلی را نگه می‌داریم تا بازگشت ممکن باشد
				update_post_meta( $id, '_texa_sku_before', $info['old'] );
				$product->set_sku( $info['new'] );
				$product->save();
				$applied[ $id ] = $info;
			} catch ( Exception $e ) {
				delete_post_meta( $id, '_texa_sku_before' );
				$failed[ $id ] = $e->getMessage();
			}
		}
	}

	texa_render_report( $plan, $conflicts, $applied, $failed, $unchanged, $empty, $apply );
}

/**
 * SKU ها را به مقدار قبل از اجرای ابزار برمی‌گرداند.
 */
function texa_sku_revert() {
	global $wpdb;

	$rows = $wpdb->get_results(
		"SELECT post_id, meta_value AS old_sku
		   FROM {$wpdb->postmeta}
		  WHERE meta_key = '_texa_sku_before'"
	);

	$done = 0;
	$fail = 0;
	foreach ( $rows as $r ) {
		$product = wc_get_product( (int) $r->post_id );
		if ( ! $product ) {
			$fail++;
			continue;
		}
		try {
			$product->set_sku( $r->old_sku );
			$product->save();
			delete_post_meta( (int) $r->post_id, '_texa_sku_before' );
			$done++;
		} catch ( Exception $e ) {
			$fail++;
		}
	}

	wp_die(
		sprintf(
			'<div style="font-family:Tahoma;direction:rtl;padding:20px">
				<h2>بازگردانی SKU</h2>
				<p>بازگردانده شد: <b>%d</b> &nbsp;|&nbsp; ناموفق: <b>%d</b></p>
			</div>',
			$done,
			$fail
		),
		'بازگردانی SKU',
		[ 'response' => 200 ]
	);
}

/**
 * خروجی HTML گزارش.
 */
function texa_render_report( $plan, $conflicts, $applied, $failed, $unchanged, $empty, $apply ) {
	$h = function ( $s ) {
		return esc_html( (string) $s );
	};

	ob_start();
	?>
	<div style="font-family:Tahoma,sans-serif;direction:rtl;padding:24px;max-width:1000px;margin:auto;line-height:1.9">
		<h1 style="margin:0 0 4px">نرمال‌سازی SKU محصولات</h1>
		<p style="color:#666;margin:0 0 20px">
			<?php echo $apply ? '<b style="color:#b00">حالت اعمال تغییرات</b>' : '<b style="color:#060">حالت گزارش — هیچ چیزی تغییر نکرد</b>'; ?>
		</p>

		<table style="border-collapse:collapse;margin-bottom:24px">
			<tr><td style="padding:4px 16px 4px 0">نیازمند اصلاح</td><td><b><?php echo count( $plan ) + count( $conflicts ); ?></b></td></tr>
			<tr><td style="padding:4px 16px 4px 0">آمادهٔ اصلاح (بدون تداخل)</td><td><b style="color:#060"><?php echo count( $plan ); ?></b></td></tr>
			<tr><td style="padding:4px 16px 4px 0">دارای تداخل — نیاز به تصمیم دستی</td><td><b style="color:#b00"><?php echo count( $conflicts ); ?></b></td></tr>
			<tr><td style="padding:4px 16px 4px 0">از قبل درست بوده</td><td><?php echo (int) $unchanged; ?></td></tr>
			<tr><td style="padding:4px 16px 4px 0">بدون SKU</td><td><?php echo (int) $empty; ?></td></tr>
			<?php if ( $apply ) : ?>
				<tr><td style="padding:4px 16px 4px 0">اعمال شد</td><td><b style="color:#060"><?php echo count( $applied ); ?></b></td></tr>
				<tr><td style="padding:4px 16px 4px 0">ناموفق</td><td><b style="color:#b00"><?php echo count( $failed ); ?></b></td></tr>
			<?php endif; ?>
		</table>

		<?php if ( $conflicts ) : ?>
			<h2 style="color:#b00">⚠️ تداخل‌ها — این‌ها اصلاح نشدند</h2>
			<p>این محصولات بعد از نرمال‌سازی SKU یکسان پیدا می‌کنند. یعنی یک قطعه دو بار روی سایت ثبت شده.
			   باید یکی را حذف یا ادغام کنید، سپس ابزار را دوباره اجرا کنید.</p>
			<table border="1" cellpadding="6" style="border-collapse:collapse;width:100%;margin-bottom:24px">
				<tr style="background:#fee"><th>SKU نهایی</th><th>محصولات درگیر</th></tr>
				<?php foreach ( $conflicts as $sku => $ids ) : ?>
					<tr>
						<td style="white-space:nowrap"><code><?php echo $h( $sku ); ?></code></td>
						<td>
							<?php foreach ( $ids as $id ) : $p = get_post( $id ); ?>
								<div>
									<a href="<?php echo esc_url( get_edit_post_link( $id ) ); ?>">#<?php echo (int) $id; ?></a>
									— <?php echo $h( $p ? $p->post_title : '?' ); ?>
									<code>[<?php echo $h( get_post_meta( $id, '_sku', true ) ); ?>]</code>
								</div>
							<?php endforeach; ?>
						</td>
					</tr>
				<?php endforeach; ?>
			</table>
		<?php endif; ?>

		<?php if ( $failed ) : ?>
			<h2 style="color:#b00">خطاها</h2>
			<table border="1" cellpadding="6" style="border-collapse:collapse;width:100%;margin-bottom:24px">
				<tr style="background:#fee"><th>شناسه</th><th>پیام</th></tr>
				<?php foreach ( $failed as $id => $msg ) : ?>
					<tr><td>#<?php echo (int) $id; ?></td><td><?php echo $h( $msg ); ?></td></tr>
				<?php endforeach; ?>
			</table>
		<?php endif; ?>

		<?php if ( $plan ) : ?>
			<h2><?php echo $apply ? 'اعمال‌شده' : 'آمادهٔ اصلاح'; ?></h2>
			<table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
				<tr style="background:#eee"><th>شناسه</th><th>SKU فعلی</th><th>SKU جدید</th><th>نام محصول</th></tr>
				<?php foreach ( $plan as $id => $info ) : ?>
					<tr>
						<td>#<?php echo (int) $id; ?></td>
						<td><code><?php echo $h( $info['old'] ); ?></code></td>
						<td><code style="color:#060"><b><?php echo $h( $info['new'] ); ?></b></code></td>
						<td><?php echo $h( $info['title'] ); ?></td>
					</tr>
				<?php endforeach; ?>
			</table>
		<?php endif; ?>

		<?php if ( ! $apply && $plan ) : ?>
			<p style="margin-top:24px;padding:16px;background:#fff8e1;border:1px solid #fc0">
				برای اعمال واقعی، اول از دیتابیس بکاپ بگیرید و سپس این آدرس را باز کنید:<br>
				<code><?php echo esc_url( admin_url( '?texa_fix_sku=1&apply=1' ) ); ?></code>
			</p>
		<?php endif; ?>
	</div>
	<?php
	wp_die( ob_get_clean(), 'نرمال‌سازی SKU', [ 'response' => 200 ] );
}
